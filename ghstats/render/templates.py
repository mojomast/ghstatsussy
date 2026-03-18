from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReportTemplate:
    key: str
    label: str
    template_name: str
    description: str
    family: str
    tone: str
    badges: tuple[str, ...]
    swatches: tuple[str, ...]


REPORT_TEMPLATES: tuple[ReportTemplate, ...] = (
    ReportTemplate("default", "Signal Glass", "report_default.html.j2", "Warm infographic glass cards with modern charts.", "Modern", "Bright / polished", ("shareable", "balanced", "charts"), ("#0f766e", "#d97706", "#1d4ed8")),
    ReportTemplate("ledger", "Maintainer's Ledger", "report_ledger.html.j2", "Editorial annual-report styling with print-inspired structure.", "Executive", "Print / formal", ("serif", "report", "boardroom"), ("#7b2d26", "#b08968", "#3b4d61")),
    ReportTemplate("transit", "Merge Line Transit Map", "report_transit.html.j2", "Route-map inspired layout with strong wayfinding cues.", "Systems", "Wayfinding / bright", ("routes", "diagram", "clear"), ("#006da8", "#ed8b00", "#00a56a")),
    ReportTemplate("archive", "Archive Exhibit", "report_archive.html.j2", "Museum-like artifact framing and curated chronology.", "Editorial", "Curated / warm", ("museum", "artifact", "story"), ("#7f5539", "#5c7c72", "#b08968")),
    ReportTemplate("scrapbook", "Indie Dev Scrapbook", "report_scrapbook.html.j2", "Playful collage layout with zine energy and stickers.", "Playful", "Loud / handmade", ("zine", "collage", "energetic"), ("#ff6b57", "#ffbd2f", "#1fb0ff")),
    ReportTemplate("orbital", "Orbital Telemetry Brief", "report_orbital.html.j2", "Mission-control telemetry report with operational tone.", "Technical", "Dark / cinematic", ("ops", "telemetry", "dense"), ("#5ad8ff", "#9ff5a4", "#f2b15d")),
    ReportTemplate("fieldnotes", "Field Notes", "report_fieldnotes.html.j2", "Research notebook styling with annotations and chapter breaks.", "Narrative", "Notebook / analog", ("research", "notes", "soft"), ("#466a62", "#b25c42", "#7d8c4c")),
    ReportTemplate("signalroom", "Signal Room", "report_signalroom.html.j2", "Broadcast-equipment inspired dark report with channel bands.", "Technical", "Broadcast / dark", ("channels", "mono", "monitor"), ("#9ff5a4", "#f2b15d", "#5ad8ff")),
    ReportTemplate("gallery", "Gallery Wall", "report_gallery.html.j2", "Poster-like asymmetry and art-directed metric framing.", "Art-directed", "Poster / asymmetry", ("poster", "framed", "bold"), ("#315ca8", "#b57f3c", "#7f3c8d")),
    ReportTemplate("tapearchive", "Tape Archive", "report_tapearchive.html.j2", "Tactile cassette-index visual language with modular strips.", "Retro tactile", "Catalog / modular", ("labels", "modular", "nostalgic"), ("#111111", "#ffb100", "#00a6a6")),
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
