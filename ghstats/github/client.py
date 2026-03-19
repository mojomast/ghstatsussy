from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.utils import parseaddr
from time import sleep
from typing import Any

import httpx

from ghstats.config import ConfigError, RuntimeConfig
from ghstats.github import queries
from ghstats.models.activity import (
    ActivityDataset,
    CommitActivity,
    ContributionDay,
    IssueActivity,
    PullRequestActivity,
    RepoActivity,
    RepoLanguage,
    ViewerProfile,
    WarningNotice,
)
from ghstats.utils.timeparse import parse_github_datetime


class GitHubApiError(RuntimeError):
    """Raised when the GitHub API returns an unrecoverable error."""


@dataclass(slots=True)
class RateLimitState:
    remaining: int | None = None
    reset_at: str | None = None


class GitHubClient:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.token = config.token_provider.get_token()
        self._rate_limit = RateLimitState()
        self._client = httpx.Client(
            timeout=config.timeout_seconds,
            headers=self._build_headers(),
        )
        self._viewer_email_candidates: set[str] = set()

    def close(self) -> None:
        self._client.close()

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": self.config.user_agent,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _record_rate_limit_headers(self, response: httpx.Response) -> None:
        remaining = response.headers.get("x-ratelimit-remaining")
        reset_at = response.headers.get("x-ratelimit-reset")
        if remaining and remaining.isdigit():
            self._rate_limit.remaining = int(remaining)
        self._rate_limit.reset_at = reset_at

    def _request_with_retries(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.config.retry_attempts + 1):
            try:
                response = self._client.request(method, url, **kwargs)
                self._record_rate_limit_headers(response)
                if response.status_code in {403, 429} and attempt < self.config.retry_attempts:
                    wait_seconds = self._rate_limit_backoff_seconds(response)
                    if wait_seconds > 0:
                        sleep(wait_seconds)
                        continue
                if response.status_code in {502, 503, 504} and attempt < self.config.retry_attempts:
                    sleep(0.5 * attempt)
                    continue
                return response
            except httpx.HTTPError as error:
                last_error = error
                if attempt < self.config.retry_attempts:
                    sleep(0.5 * attempt)
                    continue
                break
        raise GitHubApiError(f"GitHub request failed: {last_error}")

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if not self.token:
            raise ConfigError("GITHUB_TOKEN or GH_TOKEN is required for live GitHub data.")

        response = self._request_with_retries(
            "POST",
            self.config.graphql_url,
            json={"query": query, "variables": variables},
        )
        if response.status_code >= 400:
            raise GitHubApiError(self._format_error_message(response))

        payload = response.json()
        if payload.get("errors"):
            messages = "; ".join(error.get("message", "Unknown GraphQL error") for error in payload["errors"])
            raise GitHubApiError(messages)
        return payload["data"]

    def rest_get(self, path: str, **kwargs: Any) -> Any:
        response = self._request_with_retries(
            "GET",
            f"{self.config.api_base_url}{path}",
            **kwargs,
        )
        if response.status_code >= 400:
            raise GitHubApiError(self._format_error_message(response))
        return response.json()

    def _format_error_message(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        message = payload.get("message") or response.text or f"HTTP {response.status_code}"
        if self._rate_limit.remaining == 0:
            return f"GitHub rate limit exceeded. Reset at {self._rate_limit.reset_at or 'unknown time'}."
        return message

    def fetch_activity_dataset(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        include_private: bool,
    ) -> ActivityDataset:
        overview = self.graphql(
            queries.VIEWER_OVERVIEW_QUERY,
            {
                "from": start_at.isoformat(),
                "to": end_at.isoformat(),
                "repoFirst": self.config.repo_page_size,
            },
        )["viewer"]

        viewer = ViewerProfile(
            login=overview["login"],
            name=overview.get("name"),
            url=overview["url"],
            avatar_url=overview.get("avatarUrl"),
        )
        self._viewer_email_candidates = self._build_viewer_email_candidates(overview)
        self._augment_viewer_email_candidates()
        dataset = ActivityDataset(
            viewer=viewer,
            start_at=start_at,
            end_at=end_at,
            include_private=include_private,
            total_commit_contributions=overview["contributionsCollection"]["totalCommitContributions"],
            total_issue_contributions=overview["contributionsCollection"]["totalIssueContributions"],
            total_pull_request_contributions=overview["contributionsCollection"]["totalPullRequestContributions"],
            total_pull_request_review_contributions=overview["contributionsCollection"]["totalPullRequestReviewContributions"],
            restricted_contributions_count=overview["contributionsCollection"]["restrictedContributionsCount"],
        )

        repo_index: dict[str, RepoActivity] = {}
        self._merge_contribution_repos(
            repo_index,
            overview["contributionsCollection"]["commitContributionsByRepository"],
            metric_name="commit_contributions",
        )
        self._merge_contribution_repos(
            repo_index,
            overview["contributionsCollection"]["issueContributionsByRepository"],
            metric_name="issue_contributions",
        )
        self._merge_contribution_repos(
            repo_index,
            overview["contributionsCollection"]["pullRequestContributionsByRepository"],
            metric_name="pull_request_contributions",
        )
        self._merge_contribution_repos(
            repo_index,
            overview["contributionsCollection"]["pullRequestReviewContributionsByRepository"],
            metric_name="review_contributions",
        )

        for node in overview["repositories"]["nodes"]:
            repo = repo_index.get(node["id"])
            if repo is None:
                repo = self._repo_from_node(node)
                repo_index[repo.id] = repo
            repo.languages = self._languages_from_node(node.get("languages"))
        repo_has_next_page = bool(overview["repositories"]["pageInfo"].get("hasNextPage"))
        dataset.repo_scan_has_next_page = repo_has_next_page
        if repo_has_next_page:
            self._merge_viewer_repositories(repo_index, dataset, overview["repositories"]["pageInfo"].get("endCursor"))
        self._enrich_active_repo_languages(repo_index, dataset)

        calendar = overview["contributionsCollection"]["contributionCalendar"]
        dataset.contribution_days = self._calendar_days(calendar["weeks"])

        repos = list(repo_index.values())
        if not include_private:
            repos = [repo for repo in repos if not repo.is_private]
        dataset.repos = sorted(repos, key=lambda repo: repo.total_contributions(), reverse=True)

        self._populate_search_results(dataset)
        self._populate_commit_activity(dataset)
        self._append_warnings(dataset)
        return dataset

    def _merge_contribution_repos(
        self,
        repo_index: dict[str, RepoActivity],
        nodes: list[dict[str, Any]],
        *,
        metric_name: str,
    ) -> None:
        for entry in nodes:
            repo_node = entry["repository"]
            repo = repo_index.get(repo_node["id"])
            if repo is None:
                repo = self._repo_from_node(repo_node)
                repo_index[repo.id] = repo
            setattr(repo, metric_name, entry["contributions"]["totalCount"])

    def _repo_from_node(self, node: dict[str, Any]) -> RepoActivity:
        primary_language = node.get("primaryLanguage") or {}
        return RepoActivity(
            id=node["id"],
            name=node["name"],
            name_with_owner=node["nameWithOwner"],
            owner_login=node["owner"]["login"],
            url=node["url"],
            description=node.get("description"),
            is_private=node.get("isPrivate", False),
            is_fork=node.get("isFork", False),
            primary_language=primary_language.get("name"),
            primary_language_color=primary_language.get("color"),
            stargazer_count=node.get("stargazerCount", 0),
            fork_count=node.get("forkCount", 0),
            pushed_at=parse_github_datetime(node.get("pushedAt")),
            default_branch=(node.get("defaultBranchRef") or {}).get("name"),
            languages=self._languages_from_node(node.get("languages")),
        )

    def _languages_from_node(self, languages_node: dict[str, Any] | None) -> list[RepoLanguage]:
        if not languages_node:
            return []
        items: list[RepoLanguage] = []
        for edge in languages_node.get("edges", []):
            lang_node = edge.get("node") or {}
            items.append(
                RepoLanguage(
                    name=lang_node.get("name", "Unknown"),
                    color=lang_node.get("color"),
                    size=edge.get("size", 0),
                )
            )
        return items

    def _merge_viewer_repositories(
        self,
        repo_index: dict[str, RepoActivity],
        dataset: ActivityDataset,
        after: str | None,
    ) -> None:
        cursor = after
        while cursor:
            payload = self.graphql(
                queries.VIEWER_REPOSITORIES_QUERY,
                {
                    "first": self.config.repo_page_size,
                    "after": cursor,
                },
            )["viewer"]["repositories"]
            for node in payload["nodes"]:
                repo = repo_index.get(node["id"])
                if repo is None:
                    repo = self._repo_from_node(node)
                    repo_index[repo.id] = repo
                repo.languages = self._languages_from_node(node.get("languages"))
            if not payload["pageInfo"].get("hasNextPage"):
                dataset.repo_scan_has_next_page = False
                break
            cursor = payload["pageInfo"].get("endCursor")
            if not cursor:
                dataset.repo_scan_has_next_page = True
                break
        else:
            dataset.repo_scan_has_next_page = False

    def _enrich_active_repo_languages(
        self,
        repo_index: dict[str, RepoActivity],
        dataset: ActivityDataset,
    ) -> None:
        candidates = [
            repo
            for repo in repo_index.values()
            if repo.total_contributions() > 0
            and not repo.languages
            and not repo.is_fork
            and (dataset.include_private or not repo.is_private)
        ]
        if not candidates:
            return

        candidates.sort(
            key=lambda repo: (
                repo.total_contributions(),
                repo.commit_contributions,
                repo.pull_request_contributions,
                repo.review_contributions,
                repo.issue_contributions,
                repo.pushed_at.timestamp() if repo.pushed_at else 0.0,
                repo.stargazer_count,
                repo.fork_count,
            ),
            reverse=True,
        )

        truncated = False
        if len(candidates) > self.config.max_repo_language_enrichments:
            candidates = candidates[: self.config.max_repo_language_enrichments]
            truncated = True

        try:
            for start in range(0, len(candidates), self.config.repo_details_batch_size):
                batch = candidates[start : start + self.config.repo_details_batch_size]
                payload = self.graphql(
                    queries.REPOSITORY_DETAILS_QUERY,
                    {"ids": [repo.id for repo in batch]},
                )
                for node in payload.get("nodes", []):
                    if not isinstance(node, dict) or node.get("__typename") != "Repository":
                        continue
                    repo = repo_index.get(str(node.get("id") or ""))
                    if repo is None:
                        continue
                    repo.languages = self._languages_from_node(node.get("languages"))
                    primary_language = node.get("primaryLanguage") or {}
                    if not repo.primary_language:
                        repo.primary_language = primary_language.get("name")
                    if not repo.primary_language_color:
                        repo.primary_language_color = primary_language.get("color")
        except GitHubApiError as error:
            dataset.warnings.append(
                WarningNotice(
                    code="repo-language-enrichment-skipped",
                    message="Some active repository language details could not be enriched.",
                    details=str(error),
                    level="info",
                )
            )
            return

        if truncated:
            dataset.warnings.append(
                WarningNotice(
                    code="repo-language-enrichment-truncated",
                    message="Language enrichment was capped for active contributed repositories.",
                    details=(
                        f"Enriched up to {self.config.max_repo_language_enrichments} active repositories "
                        "that were missing language metadata."
                    ),
                    level="info",
                )
            )

    def _build_viewer_email_candidates(self, overview: dict[str, Any]) -> set[str]:
        login = overview["login"].strip().lower()
        candidates = {login}
        candidate_fields = [overview.get("email")]
        for value in candidate_fields:
            self._add_email_candidate(candidates, value)
        noreply_aliases = {
            f"{login}@users.noreply.github.com",
            f"+{login}@users.noreply.github.com",
        }
        candidates.update(noreply_aliases)
        return candidates

    def _augment_viewer_email_candidates(self) -> None:
        if not self.token:
            return
        try:
            payload = self.rest_get("/user/emails")
        except GitHubApiError:
            return
        if not isinstance(payload, list):
            return
        for item in payload:
            if not isinstance(item, dict):
                continue
            self._add_email_candidate(self._viewer_email_candidates, item.get("email"))

    def _add_email_candidate(self, candidates: set[str], value: str | None) -> None:
        if not value:
            return
        email = parseaddr(value)[1].strip().lower()
        if email:
            candidates.add(email)

    def _rate_limit_backoff_seconds(self, response: httpx.Response) -> float:
        retry_after = response.headers.get("retry-after")
        if retry_after and retry_after.isdigit():
            return max(float(retry_after), 0.0)
        if self._rate_limit.remaining == 0 and self._rate_limit.reset_at and self._rate_limit.reset_at.isdigit():
            reset_at = int(self._rate_limit.reset_at)
            return max(reset_at - int(datetime.now().timestamp()) + 1, 0)
        return 0.5

    def _calendar_days(self, weeks: list[dict[str, Any]]) -> list[ContributionDay]:
        days: list[ContributionDay] = []
        for week in weeks:
            for day in week["contributionDays"]:
                parsed = parse_github_datetime(day["date"])
                if parsed is None:
                    continue
                days.append(
                    ContributionDay(
                        day=parsed.date(),
                        count=day["contributionCount"],
                        weekday=day["weekday"],
                        color=day.get("color"),
                    )
                )
        return days

    def _populate_search_results(self, dataset: ActivityDataset) -> None:
        start_date = dataset.start_at.date().isoformat()
        end_date = dataset.end_at.date().isoformat()
        pr_query = queries.build_pr_search_query(dataset.viewer.login, start_date, end_date)
        merged_pr_query = queries.build_merged_pr_search_query(dataset.viewer.login, start_date, end_date)
        issue_query = queries.build_issue_search_query(dataset.viewer.login, start_date, end_date)

        pr_results, pr_total = self._search_pull_requests(pr_query)
        merged_pr_total = self._search_count(merged_pr_query, queries.SEARCH_PULL_REQUESTS_QUERY)
        issue_results, issue_total = self._search_issues(issue_query)

        dataset.pull_requests = pr_results
        dataset.issues = issue_results
        if not dataset.include_private:
            dataset.pull_requests = [pr for pr in dataset.pull_requests if not pr.repo_is_private]
            dataset.issues = [issue for issue in dataset.issues if not issue.repo_is_private]
        dataset.pull_requests_total = pr_total if dataset.include_private else len(dataset.pull_requests)
        dataset.pull_requests_merged_total = (
            merged_pr_total if dataset.include_private else sum(1 for pr in dataset.pull_requests if pr.merged)
        )
        dataset.issues_total = issue_total if dataset.include_private else len(dataset.issues)

    def _search_pull_requests(self, query: str) -> tuple[list[PullRequestActivity], int]:
        items: list[PullRequestActivity] = []
        after: str | None = None
        total = 0
        while len(items) < self.config.max_search_items:
            payload = self.graphql(
                queries.SEARCH_PULL_REQUESTS_QUERY,
                {
                    "query": query,
                    "first": self.config.search_page_size,
                    "after": after,
                },
            )["search"]
            total = payload.get("issueCount", total)
            for node in payload["nodes"]:
                if node is None:
                    continue
                created_at = parse_github_datetime(node.get("createdAt"))
                if created_at is None:
                    continue
                items.append(
                    PullRequestActivity(
                        repo_name_with_owner=node["repository"]["nameWithOwner"],
                        repo_is_private=node["repository"].get("isPrivate", False),
                        number=node["number"],
                        title=node["title"],
                        created_at=created_at,
                        url=node["url"],
                        state=node["state"],
                        merged_at=parse_github_datetime(node.get("mergedAt")),
                        additions=node.get("additions", 0),
                        deletions=node.get("deletions", 0),
                    )
                )
            if not payload["pageInfo"]["hasNextPage"]:
                break
            after = payload["pageInfo"]["endCursor"]
            if not after:
                break
        return items, total

    def _search_issues(self, query: str) -> tuple[list[IssueActivity], int]:
        items: list[IssueActivity] = []
        after: str | None = None
        total = 0
        while len(items) < self.config.max_search_items:
            payload = self.graphql(
                queries.SEARCH_ISSUES_QUERY,
                {
                    "query": query,
                    "first": self.config.search_page_size,
                    "after": after,
                },
            )["search"]
            total = payload.get("issueCount", total)
            for node in payload["nodes"]:
                if node is None:
                    continue
                created_at = parse_github_datetime(node.get("createdAt"))
                if created_at is None:
                    continue
                items.append(
                    IssueActivity(
                        repo_name_with_owner=node["repository"]["nameWithOwner"],
                        repo_is_private=node["repository"].get("isPrivate", False),
                        number=node["number"],
                        title=node["title"],
                        created_at=created_at,
                        url=node["url"],
                        state=node["state"],
                    )
                )
            if not payload["pageInfo"]["hasNextPage"]:
                break
            after = payload["pageInfo"]["endCursor"]
            if not after:
                break
        return items, total

    def _search_count(self, query: str, search_query: str) -> int:
        payload = self.graphql(
            search_query,
            {
                "query": query,
                "first": 1,
                "after": None,
            },
        )["search"]
        return int(payload.get("issueCount", 0))

    def _populate_commit_activity(self, dataset: ActivityDataset) -> None:
        commits: list[CommitActivity] = []
        selected_repos = dataset.repos[: self.config.max_repos_for_commit_scan]
        dataset.repos_scanned_for_commits = len(selected_repos)
        for repo in selected_repos:
            if repo.is_private and not dataset.include_private:
                continue
            commits.extend(self._fetch_repo_commits(repo, dataset.viewer.login, dataset.start_at, dataset.end_at))
            if len(commits) >= self.config.max_commit_details:
                break
        if len(commits) < self.config.max_commit_details:
            commits.extend(self._fetch_pull_request_commits(dataset, selected_repos))
        deduped: dict[str, CommitActivity] = {}
        for commit in commits:
            deduped[commit.sha] = commit
        dataset.commits = sorted(deduped.values(), key=lambda item: item.committed_at)

    def _fetch_pull_request_commits(
        self,
        dataset: ActivityDataset,
        selected_repos: list[RepoActivity],
    ) -> list[CommitActivity]:
        repo_lookup = {repo.name_with_owner: repo for repo in selected_repos}
        items: list[CommitActivity] = []
        seen_shas: set[str] = set()
        for pull_request in dataset.pull_requests:
            repo = repo_lookup.get(pull_request.repo_name_with_owner)
            if repo is None:
                continue
            owner = repo.owner_login
            repo_name = repo.name
            page = 1
            while len(items) < self.config.max_pull_request_commits:
                payload = self.rest_get(
                    f"/repos/{owner}/{repo_name}/pulls/{pull_request.number}/commits",
                    params={"per_page": 100, "page": page},
                )
                if not payload:
                    break
                for summary in payload:
                    if len(items) >= self.config.max_pull_request_commits:
                        return items
                    sha = str(summary.get("sha") or "")
                    if not sha or sha in seen_shas:
                        continue
                    commit_meta = summary.get("commit") or {}
                    committer_meta = commit_meta.get("committer") or {}
                    author_meta = commit_meta.get("author") or {}
                    committed_at = parse_github_datetime(committer_meta.get("date"))
                    authored_at = parse_github_datetime(author_meta.get("date"))
                    effective_at = committed_at or authored_at
                    if effective_at is None:
                        continue
                    if effective_at < dataset.start_at or effective_at > dataset.end_at:
                        continue
                    if not self._is_viewer_pull_request_commit(summary, dataset.viewer.login):
                        continue
                    detail = self.rest_get(f"/repos/{owner}/{repo_name}/commits/{sha}")
                    stats = detail.get("stats") or {}
                    author = detail.get("author") or summary.get("author") or {}
                    committer = detail.get("committer") or summary.get("committer") or {}
                    seen_shas.add(sha)
                    items.append(
                        CommitActivity(
                            repo_name_with_owner=repo.name_with_owner,
                            sha=sha,
                            message=(commit_meta.get("message") or "").splitlines()[0],
                            committed_at=effective_at,
                            url=summary.get("html_url") or detail.get("html_url") or repo.url,
                            authored_at=authored_at,
                            author_login=author.get("login"),
                            committer_login=committer.get("login"),
                            additions=stats.get("additions", 0),
                            deletions=stats.get("deletions", 0),
                        )
                    )
                if len(payload) < 100:
                    break
                page += 1
        return items

    def _is_viewer_pull_request_commit(self, summary: dict[str, Any], login: str) -> bool:
        if self._is_viewer_commit(summary, login):
            return True
        return summary.get("author") is None and summary.get("committer") is None

    def _fetch_repo_commits(
        self,
        repo: RepoActivity,
        login: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[CommitActivity]:
        owner = repo.owner_login
        repo_name = repo.name
        items: list[CommitActivity] = []

        seen_shas: set[str] = set()
        for ref_name in self._iter_repo_refs(repo):
            for page in range(1, self.config.max_commit_pages_per_repo + 1):
                try:
                    params = {
                        "since": start_at.isoformat(),
                        "until": end_at.isoformat(),
                        "per_page": 100,
                        "page": page,
                    }
                    if ref_name:
                        params["sha"] = ref_name
                    payload = self.rest_get(
                        f"/repos/{owner}/{repo_name}/commits",
                        params=params,
                    )
                except GitHubApiError as e:
                    if "empty" in str(e).lower() or "not found" in str(e).lower():
                        break
                    raise
                if not payload:
                    break
                for summary in payload:
                    if len(items) >= self.config.max_commit_details:
                        return items
                    sha = summary["sha"]
                    if sha in seen_shas:
                        continue
                    detail = self.rest_get(f"/repos/{owner}/{repo_name}/commits/{sha}")
                    if not self._is_viewer_commit(detail, login):
                        continue
                    committed_at = parse_github_datetime((detail.get("commit") or {}).get("committer", {}).get("date"))
                    if committed_at is None:
                        continue
                    authored_at = parse_github_datetime((detail.get("commit") or {}).get("author", {}).get("date"))
                    stats = detail.get("stats") or {}
                    author = detail.get("author") or {}
                    committer = detail.get("committer") or {}
                    seen_shas.add(sha)
                    items.append(
                        CommitActivity(
                            repo_name_with_owner=repo.name_with_owner,
                            sha=sha,
                            message=detail["commit"]["message"].splitlines()[0],
                            committed_at=committed_at,
                            url=detail.get("html_url", repo.url),
                            authored_at=authored_at,
                            author_login=author.get("login"),
                            committer_login=committer.get("login"),
                            additions=stats.get("additions", 0),
                            deletions=stats.get("deletions", 0),
                        )
                    )
                if len(payload) < 100:
                    break
        return items

    def _iter_repo_refs(self, repo: RepoActivity) -> list[str | None]:
        refs: list[str | None] = []
        if repo.default_branch:
            refs.append(repo.default_branch)

        owner = repo.owner_login
        repo_name = repo.name
        seen = {ref for ref in refs if ref}
        for page in range(1, self.config.max_branch_pages_per_repo + 1):
            payload = self.rest_get(
                f"/repos/{owner}/{repo_name}/branches",
                params={
                    "per_page": self.config.branch_page_size,
                    "page": page,
                },
            )
            if not payload:
                break
            for branch in payload:
                name = (branch.get("name") or "").strip()
                if name and name not in seen:
                    refs.append(name)
                    seen.add(name)
            if len(payload) < self.config.branch_page_size:
                break
        return refs or [None]

    def _is_viewer_commit(self, detail: dict[str, Any], login: str) -> bool:
        login_lower = login.strip().lower()
        author = detail.get("author") or {}
        committer = detail.get("committer") or {}
        commit_meta = detail.get("commit") or {}
        author_meta = commit_meta.get("author") or {}
        committer_meta = commit_meta.get("committer") or {}
        candidates = {
            (author.get("login") or "").strip().lower(),
            (committer.get("login") or "").strip().lower(),
        }
        if login_lower in candidates:
            return True

        emails = {
            parseaddr(author_meta.get("email") or "")[1].strip().lower(),
            parseaddr(committer_meta.get("email") or "")[1].strip().lower(),
        }
        emails.discard("")
        return any(self._email_matches_viewer(email, login_lower) for email in emails)

    def _email_matches_viewer(self, email: str, login_lower: str) -> bool:
        if email in self._viewer_email_candidates:
            return True
        return email.endswith(f"+{login_lower}@users.noreply.github.com")

    def _append_warnings(self, dataset: ActivityDataset) -> None:
        if dataset.restricted_contributions_count:
            dataset.warnings.append(
                WarningNotice(
                    code="restricted-contributions",
                    message="Some private contributions are only available as aggregate counts.",
                    details=(
                        f"GitHub reported {dataset.restricted_contributions_count} restricted contributions "
                        "in the selected window."
                    ),
                )
            )
        if dataset.commits and len(dataset.commits) > dataset.total_commit_contributions:
            dataset.warnings.append(
                WarningNotice(
                    code="commit-total-reconciled",
                    message="Commit totals were reconciled across GitHub attribution and detailed commit scanning.",
                    details=(
                        f"GitHub reported {dataset.total_commit_contributions} attributed commits while the detailed "
                        f"scan found {len(dataset.commits)} matching commits in the selected window."
                    ),
                    level="info",
                )
            )
        if not dataset.commits:
            dataset.warnings.append(
                WarningNotice(
                    code="commit-scan-empty",
                    message="No detailed commit stats were collected for the selected window.",
                    details="Overall contribution totals may still appear from GitHub's contribution calendar even when detailed commit scan coverage is empty.",
                    level="info",
                )
            )
        if len(dataset.commits) >= self.config.max_commit_details:
            dataset.warnings.append(
                WarningNotice(
                    code="commit-scan-truncated",
                    message="Detailed commit stats were capped to keep the CLI responsive.",
                    details=(
                        f"Up to {self.config.max_commit_details} commit details were fetched across "
                        f"{self.config.max_repos_for_commit_scan} repositories."
                    ),
                    level="info",
                )
            )
        if dataset.repo_scan_has_next_page:
            dataset.warnings.append(
                WarningNotice(
                    code="repo-discovery-truncated",
                    message="Repository discovery was truncated before all pushed repositories were scanned.",
                    details="The report may overrepresent older or higher-volume repositories when GitHub repository pagination is not fully exhausted.",
                    level="info",
                )
            )
        if dataset.pull_requests_total > len(dataset.pull_requests):
            dataset.warnings.append(
                WarningNotice(
                    code="pr-detail-truncated",
                    message="Pull request highlights may be based on a capped sample of authored PRs.",
                    details=(
                        f"Fetched details for {len(dataset.pull_requests)} pull requests while "
                        f"GitHub reported {dataset.pull_requests_total} total PRs in the window."
                    ),
                    level="info",
                )
            )
        if dataset.issues_total > len(dataset.issues):
            dataset.warnings.append(
                WarningNotice(
                    code="issue-detail-truncated",
                    message="Issue highlights may be based on a capped sample of authored issues.",
                    details=(
                        f"Fetched details for {len(dataset.issues)} issues while GitHub reported "
                        f"{dataset.issues_total} total issues in the window."
                    ),
                    level="info",
                )
            )
