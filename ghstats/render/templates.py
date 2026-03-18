from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReportTemplate:
    key: str
    label: str
    template_name: str
    description: str


REPORT_TEMPLATES: tuple[ReportTemplate, ...] = (
    ReportTemplate("default", "Signal Glass", "report_default.html.j2", "Warm infographic glass cards with modern charts."),
    ReportTemplate("ledger", "Maintainer's Ledger", "report_ledger.html.j2", "Editorial annual-report styling with print-inspired structure."),
    ReportTemplate("transit", "Merge Line Transit Map", "report_transit.html.j2", "Route-map inspired layout with strong wayfinding cues."),
    ReportTemplate("archive", "Archive Exhibit", "report_archive.html.j2", "Museum-like artifact framing and curated chronology."),
    ReportTemplate("scrapbook", "Indie Dev Scrapbook", "report_scrapbook.html.j2", "Playful collage layout with zine energy and stickers."),
    ReportTemplate("orbital", "Orbital Telemetry Brief", "report_orbital.html.j2", "Mission-control telemetry report with operational tone."),
    ReportTemplate("fieldnotes", "Field Notes", "report_fieldnotes.html.j2", "Research notebook styling with annotations and chapter breaks."),
    ReportTemplate("signalroom", "Signal Room", "report_signalroom.html.j2", "Broadcast-equipment inspired dark report with channel bands."),
    ReportTemplate("gallery", "Gallery Wall", "report_gallery.html.j2", "Poster-like asymmetry and art-directed metric framing."),
    ReportTemplate("tapearchive", "Tape Archive", "report_tapearchive.html.j2", "Tactile cassette-index visual language with modular strips."),
)


DEFAULT_TEMPLATE_KEY = REPORT_TEMPLATES[0].key


def get_report_template(key: str | None) -> ReportTemplate:
    wanted = (key or DEFAULT_TEMPLATE_KEY).strip().lower()
    for template in REPORT_TEMPLATES:
        if template.key == wanted:
            return template
    valid = ", ".join(template.key for template in REPORT_TEMPLATES)
    raise ValueError(f"Unknown report template '{wanted}'. Valid options: {valid}")


def template_choices() -> list[str]:
    return [template.key for template in REPORT_TEMPLATES]
