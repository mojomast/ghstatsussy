from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ghstats.analytics.metrics import build_report_context
from ghstats.config import RuntimeConfig
from ghstats.github.client import GitHubClient
from ghstats.models.activity import ActivityDataset
from ghstats.render.html import render_report_html
from ghstats.sample_data import build_sample_dataset
from ghstats.utils.timeparse import TimeWindow


@dataclass(slots=True)
class ReportArtifacts:
    dataset: ActivityDataset
    context: dict[str, Any]
    html: str


class GhStatsService:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config

    def build_artifacts(self, *, window: TimeWindow, sample_data: bool = False) -> ReportArtifacts:
        if sample_data:
            dataset = build_sample_dataset(
                window.since_spec,
                include_private=self.config.include_private,
            )
        else:
            client = GitHubClient(self.config)
            try:
                dataset = client.fetch_activity_dataset(
                    start_at=window.start_at,
                    end_at=window.end_at,
                    include_private=self.config.include_private,
                )
            finally:
                client.close()

        context = build_report_context(dataset)
        html = render_report_html(context)
        return ReportArtifacts(dataset=dataset, context=context, html=html)


def write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    return path


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
