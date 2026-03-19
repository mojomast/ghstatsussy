from __future__ import annotations

from typing import Any


MARKDOWN_PRESETS = {"profile_readme", "summary_markdown"}
DEFAULT_VISIBLE_SECTIONS = [
    "intro",
    "key_stats",
    "top_repositories",
    "recent_activity",
    "language_snapshot",
    "highlights",
    "warnings",
    "hosted_report_link",
]


def build_markdown_export(
    context: dict[str, Any],
    *,
    preset_key: str,
    options: dict[str, Any] | None = None,
) -> str:
    preset = preset_key if preset_key in MARKDOWN_PRESETS else "summary_markdown"
    options = options or {}
    compact = bool(options.get("compact", preset == "profile_readme"))
    visible_sections = _normalize_visible_sections(options.get("visibleSections"))
    text_overrides = _normalize_text_overrides(options.get("textOverrides"))
    report_link = _normalize_url(options.get("hostedReportUrl"))

    meta = context.get("meta", {})
    subject = meta.get("subject", {})
    stats_cards = context.get("stats_cards", [])
    repo_insights = context.get("repo_insights", [])
    highlights = context.get("highlights", [])
    warnings = context.get("warnings", [])
    language_slices = context.get("language_slices", [])

    lines: list[str] = []
    title = text_overrides.get("title") or _build_title(subject, preset)
    lines.append(f"# {title}")
    intro = _build_intro(meta, text_overrides, compact)
    if "intro" in visible_sections and intro:
        lines.extend(["", intro])

    if "key_stats" in visible_sections and stats_cards:
        lines.extend(["", "## Key Stats"])
        stats = stats_cards[:4] if compact else stats_cards[:8]
        for card in stats:
            label = _string(card.get("label"))
            value = _string(card.get("value"))
            if label and value:
                lines.append(f"- **{label}:** {value}")

    if "top_repositories" in visible_sections and repo_insights:
        lines.extend(["", "## Top Repositories"])
        limit = 3 if compact else 5
        for repo in repo_insights[:limit]:
            repo_name = _string(repo.get("full_name"))
            repo_url = _normalize_url(repo.get("url"))
            description = _string(repo.get("description")) or "No description provided."
            stats = repo.get("activity", {}) or {}
            stat_bits = []
            for key, label in (("commits", "commits"), ("pull_requests", "PRs"), ("issues", "issues")):
                value = stats.get(key)
                if value not in (None, ""):
                    stat_bits.append(f"{value} {label}")
            summary = f" ({', '.join(stat_bits)})" if stat_bits else ""
            if repo_name:
                if repo_url:
                    lines.append(f"- [{repo_name}]({repo_url}) - {description}{summary}")
                else:
                    lines.append(f"- **{repo_name}** - {description}{summary}")

    if "recent_activity" in visible_sections:
        period = meta.get("period", {})
        days = _string(period.get("days"))
        subtitle = _string(meta.get("subtitle"))
        lines.extend(["", "## Recent Activity"])
        if subtitle:
            lines.append(f"- {subtitle}")
        if days:
            lines.append(f"- Window: last {days} days")
        heatmap = context.get("heatmap", {}) or {}
        total = heatmap.get("total")
        if total not in (None, ""):
            lines.append(f"- Contribution calendar total: {total}")

    if "language_snapshot" in visible_sections and language_slices:
        lines.extend(["", "## Language Snapshot"])
        limit = 5 if compact else 8
        for language in language_slices[:limit]:
            name = _string(language.get("name"))
            percent = _string(language.get("percent"))
            if name:
                suffix = f" - {percent}%" if percent else ""
                lines.append(f"- {name}{suffix}")

    if "highlights" in visible_sections and highlights:
        lines.extend(["", "## Highlights"])
        limit = 4 if compact else 8
        for item in highlights[:limit]:
            title_text = _string(item.get("title"))
            text = _string(item.get("text"))
            value = _string(item.get("value"))
            if title_text and text:
                suffix = f" ({value})" if value and value not in text else ""
                lines.append(f"- **{title_text}:** {text}{suffix}")

    if "warnings" in visible_sections and warnings and not compact:
        lines.extend(["", "## Notes"])
        for warning in warnings:
            message = _string(warning.get("message"))
            details = _string(warning.get("details"))
            if message:
                if details:
                    lines.append(f"- **{message}** - {details}")
                else:
                    lines.append(f"- **{message}**")

    if "hosted_report_link" in visible_sections and report_link:
        lines.extend(["", f"[View the full hosted report]({report_link})"])

    return "\n".join(_trim_blank_edges(lines)).strip() + "\n"


def render_markdown_preview(markdown_body: str) -> str:
    paragraphs = [segment.strip() for segment in markdown_body.split("\n\n") if segment.strip()]
    html_parts: list[str] = []
    for paragraph in paragraphs:
        lines = [line.rstrip() for line in paragraph.splitlines() if line.strip()]
        if not lines:
            continue
        if all(line.startswith("- ") for line in lines):
            html_parts.append("<ul>" + "".join(f"<li>{_markdown_inline(line[2:])}</li>" for line in lines) + "</ul>")
            continue
        first = lines[0]
        if first.startswith("### "):
            html_parts.append(f"<h3>{_markdown_inline(first[4:])}</h3>")
            continue
        if first.startswith("## "):
            html_parts.append(f"<h2>{_markdown_inline(first[3:])}</h2>")
            continue
        if first.startswith("# "):
            html_parts.append(f"<h1>{_markdown_inline(first[2:])}</h1>")
            continue
        html_parts.append(f"<p>{_markdown_inline(' '.join(lines))}</p>")
    return "\n".join(html_parts)


def _build_title(subject: dict[str, Any], preset: str) -> str:
    login = _string(subject.get("login")) or "github-user"
    if preset == "profile_readme":
        return f"Hi, I'm {login}"
    return f"GitHub Activity Summary for @{login}"


def _build_intro(meta: dict[str, Any], text_overrides: dict[str, str], compact: bool) -> str:
    tagline = text_overrides.get("tagline")
    if tagline:
        return tagline
    subtitle = _string(meta.get("subtitle"))
    period = meta.get("period", {})
    label = _string(period.get("label"))
    if compact and subtitle:
        return subtitle
    if subtitle and label:
        return f"{subtitle}. Covering {label}."
    return subtitle or label or ""


def _normalize_visible_sections(value: Any) -> list[str]:
    if not isinstance(value, list):
        return list(DEFAULT_VISIBLE_SECTIONS)
    seen: list[str] = []
    for item in value:
        section = _string(item)
        if section and section in DEFAULT_VISIBLE_SECTIONS and section not in seen:
            seen.append(section)
    return seen or list(DEFAULT_VISIBLE_SECTIONS)


def _normalize_text_overrides(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, raw in value.items():
        text = _string(raw)
        if text:
            normalized[str(key)] = text
    return normalized


def _normalize_url(value: Any) -> str | None:
    text = _string(value)
    if not text or not text.startswith(("https://", "http://")):
        return None
    return text


def _string(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _trim_blank_edges(lines: list[str]) -> list[str]:
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _markdown_inline(text: str) -> str:
    import html
    import re

    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\[(.+?)\]\((https?://[^\s)]+)\)", r'<a href="\2">\1</a>', escaped)
    return escaped
