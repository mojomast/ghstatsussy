from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from typing import cast

from ghstats.models.activity import ActivityDataset
from ghstats.utils.timeparse import iter_dates


def commits_by_day(dataset: ActivityDataset) -> list[dict[str, int | str]]:
    counts = Counter(commit.committed_at.date() for commit in dataset.commits)
    return [
        {"date": day.isoformat(), "count": counts.get(day, 0)}
        for day in iter_dates(dataset.start_at.date(), dataset.end_at.date())
    ]


def lines_by_day(dataset: ActivityDataset) -> list[dict[str, int | str]]:
    totals: dict[date, dict[str, int]] = defaultdict(lambda: {"additions": 0, "deletions": 0})
    for commit in dataset.commits:
        day = commit.committed_at.date()
        totals[day]["additions"] += commit.additions
        totals[day]["deletions"] += commit.deletions

    return [
        {
            "date": day.isoformat(),
            "additions": totals[day]["additions"],
            "deletions": totals[day]["deletions"],
        }
        for day in iter_dates(dataset.start_at.date(), dataset.end_at.date())
    ]


def activity_heatmap(dataset: ActivityDataset) -> list[list[int]]:
    matrix = [[0 for _ in range(24)] for _ in range(7)]
    for commit in dataset.commits:
        matrix[commit.committed_at.weekday()][commit.committed_at.hour] += 1
    return matrix


def language_breakdown(dataset: ActivityDataset) -> list[dict[str, int | float | str | None]]:
    totals: dict[str, dict[str, int | str | None]] = {}
    for repo in dataset.repos:
        for language in repo.languages:
            if language.name not in totals:
                totals[language.name] = {
                    "value": 0,
                    "color": language.color or "#6b7280",
                    "repo_count": 0,
                }
            bucket = totals[language.name]
            bucket["value"] = cast(int, bucket["value"]) + language.size
            bucket["repo_count"] = cast(int, bucket["repo_count"]) + 1

    total_size = sum(cast(int, item["value"]) for item in totals.values()) or 1
    items = []
    for name, item in totals.items():
        value = cast(int, item["value"])
        items.append(
            {
                "name": name,
                "value": value,
                "percent": round((value / total_size) * 100, 2),
                "color": item["color"],
                "repo_count": item["repo_count"],
            }
        )
    return sorted(items, key=lambda entry: entry["value"], reverse=True)


def top_repositories(dataset: ActivityDataset, limit: int = 8) -> list[dict[str, object]]:
    detailed_commit_counts = Counter(commit.repo_name_with_owner for commit in dataset.commits)
    repos = sorted(
        dataset.repos,
        key=lambda repo: (
            repo.pushed_at.timestamp() if repo.pushed_at else 0.0,
            detailed_commit_counts.get(repo.name_with_owner, 0),
            repo.commit_contributions,
            repo.total_contributions(),
            repo.stargazer_count,
        ),
        reverse=True,
    )
    items = []
    for repo in repos[:limit]:
        items.append(
            {
                "name": repo.name,
                "full_name": repo.name_with_owner,
                "url": repo.url,
                "description": repo.description,
                "primary_language": repo.primary_language,
                "stars": repo.stargazer_count,
                "forks": repo.fork_count,
                "activity": {
                    "commits": max(repo.commit_contributions, detailed_commit_counts.get(repo.name_with_owner, 0)),
                    "pull_requests": repo.pull_request_contributions,
                    "issues": repo.issue_contributions,
                    "reviews": repo.review_contributions,
                },
                "highlights": build_repo_highlights(repo),
                "health": {
                    "last_active_at": repo.pushed_at.isoformat() if repo.pushed_at else None,
                    "opened": repo.issue_contributions,
                    "merged_prs": repo.pull_request_contributions,
                },
            }
        )
    return items


def build_repo_highlights(repo: object) -> list[str]:
    highlights: list[str] = []
    commit_count = getattr(repo, "commit_contributions", 0)
    if commit_count:
        highlights.append(f"{commit_count} commit contributions")
    pr_count = getattr(repo, "pull_request_contributions", 0)
    if pr_count:
        highlights.append(f"{pr_count} pull requests opened")
    review_count = getattr(repo, "review_contributions", 0)
    if review_count:
        highlights.append(f"{review_count} reviews submitted")
    if getattr(repo, "is_private", False):
        highlights.append("Private repository")
    if getattr(repo, "is_fork", False):
        highlights.append("Forked project")
    return highlights[:3]
