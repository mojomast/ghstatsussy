from __future__ import annotations

import random
from datetime import datetime, time, timedelta, timezone

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
from ghstats.utils.timeparse import build_time_window, iter_dates


def build_sample_dataset(since: str = "30d", *, include_private: bool = True) -> ActivityDataset:
    window = build_time_window(since, now=datetime(2026, 3, 18, 12, 0, tzinfo=timezone.utc))
    rng = random.Random(42)

    viewer = ViewerProfile(
        login="octo-builder",
        name="Octo Builder",
        url="https://github.com/octo-builder",
        avatar_url="https://avatars.githubusercontent.com/u/583231?v=4",
    )

    repos = [
        RepoActivity(
            id="R_demo_1",
            name="signalboard",
            name_with_owner="octo-builder/signalboard",
            owner_login="octo-builder",
            url="https://github.com/octo-builder/signalboard",
            description="Team observability dashboard for release and incident visibility.",
            primary_language="Python",
            primary_language_color="#3572A5",
            stargazer_count=88,
            fork_count=12,
            languages=[
                RepoLanguage("Python", "#3572A5", 84000),
                RepoLanguage("HTML", "#e34c26", 18000),
                RepoLanguage("CSS", "#663399", 9000),
            ],
            commit_contributions=34,
            issue_contributions=5,
            pull_request_contributions=8,
            review_contributions=11,
        ),
        RepoActivity(
            id="R_demo_2",
            name="flare-ui",
            name_with_owner="octo-builder/flare-ui",
            owner_login="octo-builder",
            url="https://github.com/octo-builder/flare-ui",
            description="Marketing microsite with component-driven interactions.",
            primary_language="TypeScript",
            primary_language_color="#3178c6",
            stargazer_count=54,
            fork_count=6,
            languages=[
                RepoLanguage("TypeScript", "#3178c6", 71000),
                RepoLanguage("CSS", "#663399", 22000),
                RepoLanguage("JavaScript", "#f1e05a", 14000),
            ],
            commit_contributions=22,
            issue_contributions=4,
            pull_request_contributions=6,
            review_contributions=3,
        ),
        RepoActivity(
            id="R_demo_3",
            name="rusty-cache",
            name_with_owner="octo-builder/rusty-cache",
            owner_login="octo-builder",
            url="https://github.com/octo-builder/rusty-cache",
            description="Experimental cache service with a compact CLI control plane.",
            primary_language="Rust",
            primary_language_color="#dea584",
            stargazer_count=39,
            fork_count=3,
            languages=[
                RepoLanguage("Rust", "#dea584", 68000),
                RepoLanguage("Shell", "#89e051", 4000),
            ],
            commit_contributions=17,
            issue_contributions=2,
            pull_request_contributions=3,
            review_contributions=2,
        ),
        RepoActivity(
            id="R_demo_4",
            name="vault-notes",
            name_with_owner="octo-builder/vault-notes",
            owner_login="octo-builder",
            url="https://github.com/octo-builder/vault-notes",
            description="Private knowledge base sync tooling.",
            is_private=True,
            primary_language="Go",
            primary_language_color="#00ADD8",
            stargazer_count=0,
            fork_count=0,
            languages=[
                RepoLanguage("Go", "#00ADD8", 51000),
                RepoLanguage("Makefile", "#427819", 2000),
            ],
            commit_contributions=13,
            issue_contributions=1,
            pull_request_contributions=2,
            review_contributions=0,
        ),
    ]

    contribution_days: list[ContributionDay] = []
    commits: list[CommitActivity] = []
    pull_requests: list[PullRequestActivity] = []
    issues: list[IssueActivity] = []
    total_commit_contributions = 0

    all_dates = iter_dates(window.start_date, window.end_date)
    for day in all_dates:
        base = 0
        if day.weekday() < 5:
            base = rng.randint(0, 5)
        else:
            base = rng.randint(0, 2)
        if rng.random() > 0.85:
            base += rng.randint(2, 5)
        contribution_days.append(
            ContributionDay(day=day, count=base, weekday=day.weekday(), color=None)
        )
        commit_count = max(0, base - rng.randint(0, 2))
        total_commit_contributions += commit_count
        for idx in range(commit_count):
            repo = repos[(idx + day.day) % len(repos)]
            committed_at = datetime.combine(
                day,
                time(hour=(9 + idx * 2 + rng.randint(0, 2)) % 24, minute=rng.choice([5, 15, 35, 50])),
                tzinfo=timezone.utc,
            )
            additions = rng.randint(8, 180)
            deletions = rng.randint(0, 90)
            commits.append(
                CommitActivity(
                    repo_name_with_owner=repo.name_with_owner,
                    sha=f"{day.strftime('%Y%m%d')}{idx:02d}",
                    message=rng.choice(
                        [
                            "Refine report layout",
                            "Improve metrics aggregation",
                            "Fix GitHub pagination edge case",
                            "Polish responsive card spacing",
                            "Add repo language summary",
                        ]
                    ),
                    committed_at=committed_at,
                    url=f"{repo.url}/commit/{day.strftime('%Y%m%d')}{idx:02d}",
                    additions=additions,
                    deletions=deletions,
                )
            )

        if rng.random() > 0.72:
            repo = rng.choice(repos)
            issues.append(
                IssueActivity(
                    repo_name_with_owner=repo.name_with_owner,
                    repo_is_private=repo.is_private,
                    number=100 + len(issues),
                    title=rng.choice(
                        [
                            "Investigate flaky API retry behavior",
                            "Document contribution heatmap legend",
                            "Tune chart color contrast on mobile",
                        ]
                    ),
                    created_at=datetime.combine(day, time(hour=11, minute=30), tzinfo=timezone.utc),
                    url=f"{repo.url}/issues/{100 + len(issues)}",
                    state=rng.choice(["OPEN", "CLOSED"]),
                )
            )

        if rng.random() > 0.68:
            repo = rng.choice(repos)
            merged = rng.random() > 0.3
            pull_requests.append(
                PullRequestActivity(
                    repo_name_with_owner=repo.name_with_owner,
                    repo_is_private=repo.is_private,
                    number=50 + len(pull_requests),
                    title=rng.choice(
                        [
                            "Add demo export pipeline",
                            "Refactor contribution parsing",
                            "Improve HTML card motion timing",
                            "Expose JSON serialization hook",
                        ]
                    ),
                    created_at=datetime.combine(day, time(hour=14, minute=10), tzinfo=timezone.utc),
                    url=f"{repo.url}/pull/{50 + len(pull_requests)}",
                    state="MERGED" if merged else "OPEN",
                    merged_at=(
                        datetime.combine(day + timedelta(days=1), time(hour=9, minute=0), tzinfo=timezone.utc)
                        if merged
                        else None
                    ),
                    additions=rng.randint(24, 420),
                    deletions=rng.randint(5, 180),
                )
            )

    filtered_repos = repos if include_private else [repo for repo in repos if not repo.is_private]
    filtered_commits = commits if include_private else [
        commit for commit in commits if "vault-notes" not in commit.repo_name_with_owner
    ]
    filtered_pull_requests = pull_requests if include_private else [
        pr for pr in pull_requests if not pr.repo_is_private
    ]
    filtered_issues = issues if include_private else [
        issue for issue in issues if not issue.repo_is_private
    ]
    filtered_commit_contributions = sum(
        repo.commit_contributions for repo in filtered_repos
    )

    dataset = ActivityDataset(
        viewer=viewer,
        start_at=window.start_at,
        end_at=window.end_at,
        include_private=include_private,
        repos=filtered_repos,
        commits=sorted(filtered_commits, key=lambda item: item.committed_at),
        pull_requests=sorted(filtered_pull_requests, key=lambda item: item.created_at),
        issues=sorted(filtered_issues, key=lambda item: item.created_at),
        contribution_days=contribution_days,
        warnings=[
            WarningNotice(
                code="sample-data",
                message="This report was generated from deterministic sample data.",
                level="info",
                details="Use GITHUB_TOKEN for live GitHub activity.",
            )
        ],
        total_commit_contributions=(
            total_commit_contributions if include_private else filtered_commit_contributions
        ),
        total_issue_contributions=len(filtered_issues),
        total_pull_request_contributions=len(filtered_pull_requests),
        total_pull_request_review_contributions=16,
        pull_requests_total=len(filtered_pull_requests),
        pull_requests_merged_total=sum(1 for pr in filtered_pull_requests if pr.merged),
        issues_total=len(filtered_issues),
        restricted_contributions_count=7,
    )
    return dataset
