from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
        for repo in selected_repos:
            if repo.is_private and not dataset.include_private:
                continue
            commits.extend(self._fetch_repo_commits(repo, dataset.viewer.login, dataset.start_at, dataset.end_at))
            if len(commits) >= self.config.max_commit_details:
                break
        dataset.commits = sorted(commits, key=lambda item: item.committed_at)

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

        for page in range(1, self.config.max_commit_pages_per_repo + 1):
            payload = self.rest_get(
                f"/repos/{owner}/{repo_name}/commits",
                params={
                    "author": login,
                    "since": start_at.isoformat(),
                    "until": end_at.isoformat(),
                    "per_page": 100,
                    "page": page,
                },
            )
            if not payload:
                break
            for summary in payload:
                if len(items) >= self.config.max_commit_details:
                    return items
                sha = summary["sha"]
                detail = self.rest_get(f"/repos/{owner}/{repo_name}/commits/{sha}")
                committed_at = parse_github_datetime(detail["commit"]["author"]["date"])
                if committed_at is None:
                    continue
                stats = detail.get("stats") or {}
                items.append(
                    CommitActivity(
                        repo_name_with_owner=repo.name_with_owner,
                        sha=sha,
                        message=detail["commit"]["message"].splitlines()[0],
                        committed_at=committed_at,
                        url=detail.get("html_url", repo.url),
                        additions=stats.get("additions", 0),
                        deletions=stats.get("deletions", 0),
                    )
                )
            if len(payload) < 100:
                break
        return items

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
        if not dataset.commits:
            dataset.warnings.append(
                WarningNotice(
                    code="commit-scan-empty",
                    message="No detailed commit stats were collected for the selected window.",
                    details="Commit totals may still appear from the contribution calendar.",
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
