from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape


TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["tojson_pretty"] = lambda value: json.dumps(value, ensure_ascii=False)
    return env


def render_report_html(context: dict[str, Any]) -> str:
    template = _environment().get_template("report.html.j2")
    chart_payload = {
        "commits": context["chart_datasets"]["commits_timeline"],
        "loc": context["chart_datasets"]["loc_timeline"],
        "languages": context["chart_datasets"]["languages"],
        "weekdayHours": context["chart_datasets"]["weekday_hours"],
    }
    return template.render(
        context=context,
        chart_payload=chart_payload,
        chart_payload_json=json.dumps(chart_payload),
    )
