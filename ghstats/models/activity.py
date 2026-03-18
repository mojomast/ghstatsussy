from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(slots=True)
class ViewerProfile:
    login: str
    name: str | None
    url: str
    avatar_url: str | None


@dataclass(slots=True)
class RepoLanguage:
    name: str
    color: str | None
    size: int


@dataclass(slots=True)
class RepoActivity:
    id: str
    name: str
    name_with_owner: str
    owner_login: str
    url: str
    description: str | None = None
    is_private: bool = False
    is_fork: bool = False
    primary_language: str | None = None
    primary_language_color: str | None = None
    stargazer_count: int = 0
    fork_count: int = 0
    pushed_at: datetime | None = None
    languages: list[RepoLanguage] = field(default_factory=list)
    commit_contributions: int = 0
    issue_contributions: int = 0
    pull_request_contributions: int = 0
    review_contributions: int = 0

    def total_contributions(self) -> int:
        return (
            self.commit_contributions
            + self.issue_contributions
            + self.pull_request_contributions
            + self.review_contributions
        )


@dataclass(slots=True)
class CommitActivity:
    repo_name_with_owner: str
    sha: str
    message: str
    committed_at: datetime
    url: str
    additions: int = 0
    deletions: int = 0

    @property
    def total_changes(self) -> int:
        return self.additions + self.deletions


@dataclass(slots=True)
class PullRequestActivity:
    repo_name_with_owner: str
    repo_is_private: bool
    number: int
    title: str
    created_at: datetime
    url: str
    state: str
    merged_at: datetime | None = None
    additions: int = 0
    deletions: int = 0

    @property
    def merged(self) -> bool:
        return self.merged_at is not None or self.state.upper() == "MERGED"


@dataclass(slots=True)
class IssueActivity:
    repo_name_with_owner: str
    repo_is_private: bool
    number: int
    title: str
    created_at: datetime
    url: str
    state: str


@dataclass(slots=True)
class ContributionDay:
    day: date
    count: int
    weekday: int
    color: str | None = None


@dataclass(slots=True)
class WarningNotice:
    code: str
    message: str
    level: str = "warning"
    details: str | None = None


@dataclass(slots=True)
class ActivityDataset:
    viewer: ViewerProfile
    start_at: datetime
    end_at: datetime
    include_private: bool
    repos: list[RepoActivity] = field(default_factory=list)
    commits: list[CommitActivity] = field(default_factory=list)
    pull_requests: list[PullRequestActivity] = field(default_factory=list)
    issues: list[IssueActivity] = field(default_factory=list)
    contribution_days: list[ContributionDay] = field(default_factory=list)
    warnings: list[WarningNotice] = field(default_factory=list)
    total_commit_contributions: int = 0
    total_issue_contributions: int = 0
    total_pull_request_contributions: int = 0
    total_pull_request_review_contributions: int = 0
    pull_requests_total: int = 0
    pull_requests_merged_total: int = 0
    issues_total: int = 0
    restricted_contributions_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
