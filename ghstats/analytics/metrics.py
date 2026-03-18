from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from statistics import mean
from typing import Any

from ghstats.analytics.aggregations import (
    activity_heatmap,
    commits_by_day,
    language_breakdown,
    lines_by_day,
    top_repositories,
)
from ghstats.models.activity import ActivityDataset


WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def build_report_context(dataset: ActivityDataset) -> dict[str, Any]:
    commit_series = commits_by_day(dataset)
    line_series = lines_by_day(dataset)
    heatmap_matrix = activity_heatmap(dataset)
    languages = language_breakdown(dataset)
    streaks = compute_streaks(commit_series)
    highlights = build_highlights(dataset, commit_series, line_series, streaks)

    return {
        "meta": {
            "title": "GitHub Activity Report",
            "subtitle": f"A contribution snapshot for @{dataset.viewer.login}",
            "subject": {
                "login": dataset.viewer.login,
                "display_name": dataset.viewer.name,
                "avatar_url": dataset.viewer.avatar_url,
                "profile_url": dataset.viewer.url,
            },
            "period": {
                "label": f"{dataset.start_at.date().isoformat()} to {dataset.end_at.date().isoformat()}",
                "start": dataset.start_at.date().isoformat(),
                "end": dataset.end_at.date().isoformat(),
                "timezone": "UTC",
                "days": (dataset.end_at.date() - dataset.start_at.date()).days + 1,
            },
            "generated_at": dataset.end_at.isoformat(),
            "generator": {
                "name": "ghstats",
                "version": "0.1.0",
            },
            "links": {
                "repository_url": "https://github.com/mojomast/ghstatsussy",
                "repository_label": "mojomast/ghstatsussy",
                "ussyverse_url": "https://ussy.host",
                "ussyverse_label": "ussyverse",
            },
        },
        "stats_cards": build_stats_cards(dataset, commit_series, line_series, streaks),
        "chart_datasets": {
            "commits_timeline": {
                "title": "Commits per Day",
                "labels": [item["date"] for item in commit_series],
                "series": [
                    {
                        "id": "commits",
                        "label": "Commits",
                        "values": [item["count"] for item in commit_series],
                        "color": "#0f766e",
                    }
                ],
            },
            "loc_timeline": {
                "title": "Lines Added vs Deleted",
                "labels": [item["date"] for item in line_series],
                "series": [
                    {
                        "id": "additions",
                        "label": "Added",
                        "values": [item["additions"] for item in line_series],
                        "color": "#16a34a",
                    },
                    {
                        "id": "deletions",
                        "label": "Deleted",
                        "values": [item["deletions"] for item in line_series],
                        "color": "#dc2626",
                    },
                ],
            },
            "weekday_hours": {
                "title": "Activity by Weekday and Hour",
                "x_labels": [f"{hour:02d}:00" for hour in range(24)],
                "y_labels": WEEKDAYS,
                "matrix": heatmap_matrix,
                "min": 0,
                "max": max((max(row) for row in heatmap_matrix), default=0),
            },
            "languages": {
                "title": "Top Languages",
                "labels": [item["name"] for item in languages[:8]],
                "values": [item["value"] for item in languages[:8]],
                "colors": [item["color"] for item in languages[:8]],
            },
        },
        "heatmap": build_calendar_heatmap(dataset, streaks),
        "language_slices": languages[:8],
        "repo_insights": top_repositories(dataset),
        "highlights": highlights,
        "warnings": [asdict(warning) for warning in dataset.warnings],
    }


def build_stats_cards(
    dataset: ActivityDataset,
    commit_series: list[dict[str, int | str]],
    line_series: list[dict[str, int | str]],
    streaks: dict[str, int],
) -> list[dict[str, Any]]:
    commit_counts = [int(item["count"]) for item in commit_series]
    added_total = sum(int(item["additions"]) for item in line_series)
    deleted_total = sum(int(item["deletions"]) for item in line_series)
    avg_commits = round(dataset.total_commit_contributions / max(len(commit_counts), 1), 2) if commit_counts else 0.0

    return [
        stat_card("commits", "Total commits", dataset.total_commit_contributions, "commits", "teal"),
        stat_card("avg-commits", "Avg commits/day", avg_commits, None, "amber"),
        stat_card("loc-added", "Lines added", added_total, "lines", "green"),
        stat_card("loc-deleted", "Lines deleted", deleted_total, "lines", "red"),
        stat_card("prs", "PRs opened / merged", f"{dataset.pull_requests_total} / {dataset.pull_requests_merged_total}", None, "slate"),
        stat_card("issues", "Issues opened", dataset.issues_total, "issues", "blue"),
        stat_card("repos", "Repos contributed to", len({repo.name_with_owner for repo in dataset.repos}), "repos", "violet"),
        stat_card("streak", "Current / longest streak", f"{streaks['current']} / {streaks['longest']}", "days", "orange"),
    ]


def stat_card(card_id: str, label: str, value: Any, unit: str | None, accent: str) -> dict[str, Any]:
    return {
        "id": card_id,
        "label": label,
        "value": str(value),
        "raw_value": value,
        "unit": unit,
        "delta": {"value": None, "label": None, "direction": None},
        "accent": accent,
        "icon": None,
    }


def compute_streaks(commit_series: list[dict[str, int | str]]) -> dict[str, int]:
    longest = 0
    current = 0
    running = 0
    for item in commit_series:
        count = int(item["count"])
        if count > 0:
            running += 1
            longest = max(longest, running)
        else:
            running = 0
    for item in reversed(commit_series):
        if int(item["count"]) > 0:
            current += 1
        else:
            break
    return {"current": current, "longest": longest}


def build_calendar_heatmap(dataset: ActivityDataset, streaks: dict[str, int]) -> dict[str, Any]:
    weeks: list[dict[str, Any]] = []
    current_week: list[dict[str, Any]] = []
    max_count = max((day.count for day in dataset.contribution_days), default=0)
    for day in dataset.contribution_days:
        level = 0 if max_count == 0 else min(4, round((day.count / max_count) * 4))
        current_week.append(
            {
                "date": day.day.isoformat(),
                "count": day.count,
                "level": level,
                "tooltip": f"{day.day.isoformat()}: {day.count} contributions",
            }
        )
        if len(current_week) == 7:
            weeks.append({"label": current_week[0]["date"], "days": current_week})
            current_week = []
    if current_week:
        while len(current_week) < 7:
            current_week.append(
                {"date": "", "count": 0, "level": 0, "tooltip": "No data"}
            )
        weeks.append({"label": current_week[0]["date"], "days": current_week})

    return {
        "title": "Contribution Calendar",
        "weeks": weeks,
        "total": sum(day.count for day in dataset.contribution_days),
        "streak": streaks,
    }


def build_highlights(
    dataset: ActivityDataset,
    commit_series: list[dict[str, int | str]],
    line_series: list[dict[str, int | str]],
    streaks: dict[str, int],
) -> list[dict[str, Any]]:
    weekday_counter = Counter(commit.committed_at.weekday() for commit in dataset.commits)
    hour_counter = Counter(commit.committed_at.hour for commit in dataset.commits)
    most_active_weekday = WEEKDAYS[weekday_counter.most_common(1)[0][0]] if weekday_counter else "N/A"
    most_active_hour = f"{hour_counter.most_common(1)[0][0]:02d}:00" if hour_counter else "N/A"
    most_productive_day = max(commit_series, key=lambda item: int(item["count"]), default={"date": "N/A", "count": 0})
    largest_commit = max(dataset.commits, key=lambda commit: commit.total_changes, default=None)
    weekend_commits = sum(
        1 for commit in dataset.commits if commit.committed_at.weekday() >= 5
    )
    weekday_commits = len(dataset.commits) - weekend_commits
    ratio = round(weekday_commits / weekend_commits, 2) if weekend_commits else None
    avg_commit_size = round(
        mean(commit.total_changes for commit in dataset.commits), 2
    ) if dataset.commits else 0

    highlights: list[dict[str, Any]] = [
        {
            "kind": "trend",
            "title": "Most active weekday",
            "text": f"{most_active_weekday} is your busiest commit day.",
            "value": most_active_weekday,
        },
        {
            "kind": "trend",
            "title": "Most active hour",
            "text": f"Peak coding time lands around {most_active_hour} UTC.",
            "value": most_active_hour,
        },
        {
            "kind": "streak",
            "title": "Longest streak",
            "text": f"You sustained a {streaks['longest']}-day commit streak.",
            "value": str(streaks["longest"]),
        },
        {
            "kind": "milestone",
            "title": "Most productive day",
            "text": (
                f"{most_productive_day['date']} led the chart with "
                f"{most_productive_day['count']} commits."
            ),
            "value": str(most_productive_day["count"]),
        },
        {
            "kind": "note",
            "title": "Average commit size",
            "text": f"Your average detailed commit changed {avg_commit_size} lines.",
            "value": str(avg_commit_size),
        },
        {
            "kind": "note",
            "title": "Weekday vs weekend ratio",
            "text": (
                f"Weekday activity outweighs weekend commits by {ratio}:1."
                if ratio is not None
                else "All detailed commits landed on weekdays in this window."
            ),
            "value": str(ratio) if ratio is not None else "weekday-only",
        },
    ]

    if largest_commit is not None:
        highlights.append(
            {
                "kind": "repo",
                "title": "Largest commit",
                "text": (
                    f"{largest_commit.repo_name_with_owner} had the largest detailed commit "
                    f"at {largest_commit.total_changes} changed lines."
                ),
                "value": str(largest_commit.total_changes),
            }
        )

    top_loc_day = max(
        line_series,
        key=lambda item: int(item["additions"]) + int(item["deletions"]),
        default={"date": "N/A", "additions": 0, "deletions": 0},
    )
    highlights.append(
        {
            "kind": "milestone",
            "title": "Highest code churn",
            "text": (
                f"{top_loc_day['date']} moved {int(top_loc_day['additions']) + int(top_loc_day['deletions'])} lines."
            ),
            "value": str(int(top_loc_day["additions"]) + int(top_loc_day["deletions"])),
        }
    )

    return highlights
