from __future__ import annotations

import re
import unicodedata
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ghstats.render.templates import DEFAULT_TEMPLATE_KEY, template_choices


TITLE_CONTROL_RE = re.compile(r"[\x00-\x1F\x7F]")
ALLOWED_SINCE_SPECS = {"7d", "30d", "90d", "180d", "365d"}


class ReportVisibility(str, Enum):
    private = "private"
    unlisted = "unlisted"
    public = "public"


class ReportTemplateKey(str, Enum):
    default = "default"
    ledger = "ledger"
    transit = "transit"
    archive = "archive"
    scrapbook = "scrapbook"
    orbital = "orbital"
    fieldnotes = "fieldnotes"
    signalroom = "signalroom"
    gallery = "gallery"
    tapearchive = "tapearchive"
    cyberpunk = "cyberpunk"
    glassmorphism = "glassmorphism"
    brutalism = "brutalism"
    retro_os = "retro_os"
    holo = "holo"
    synthwave = "synthwave"
    paper = "paper"
    monochrome = "monochrome"
    matrix = "matrix"
    liquid = "liquid"


class ReportCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    since_spec: str = Field(default="30d")
    title: str | None = Field(default=None, max_length=120)
    include_private: bool = False
    visibility: ReportVisibility = ReportVisibility.unlisted
    sample_data: bool = False
    store_metadata: bool = False
    expires_in_days: int = Field(default=14, ge=1, le=90)
    template_key: ReportTemplateKey = ReportTemplateKey(DEFAULT_TEMPLATE_KEY)

    @field_validator("since_spec", mode="before")
    @classmethod
    def validate_since_spec(cls, value: object) -> str:
        since = unicodedata.normalize("NFKC", str(value)).strip().lower()
        if since not in ALLOWED_SINCE_SPECS:
            raise ValueError("Invalid time window.")
        return since

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object | None) -> str | None:
        if value is None:
            return None
        title = " ".join(unicodedata.normalize("NFKC", str(value)).split())
        if not title:
            return None
        if TITLE_CONTROL_RE.search(title):
            raise ValueError("Title contains control characters.")
        return title

    @model_validator(mode="after")
    def validate_policy(self) -> "ReportCreatePayload":
        if self.include_private and self.visibility is not ReportVisibility.private:
            raise ValueError("Private activity requires private visibility.")
        if self.visibility is ReportVisibility.public and self.expires_in_days > 30:
            raise ValueError("Public reports must expire within 30 days.")
        return self


class ReportSummary(BaseModel):
    id: str
    slug: str
    title: str
    since_spec: str
    visibility: str
    include_private: bool
    status: str
    generated_at: str | None
    share_url: str
    host_url: str | None = None
    store_metadata: bool
    expires_at: str | None
    latest_job_id: str | None = None
    template_key: str


class ViewerSummary(BaseModel):
    id: str
    login: str
    name: str | None
    avatar_url: str | None
    profile_url: str | None
    email: str | None


class ExportCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exportType: str = Field(min_length=3, max_length=24)
    options: dict = Field(default_factory=dict)

    @field_validator("exportType", mode="before")
    @classmethod
    def normalize_export_type(cls, value: object) -> str:
        export_type = unicodedata.normalize("NFKC", str(value)).strip().lower()
        if export_type not in {"pdf", "png", "html", "markdown"}:
            raise ValueError("Unsupported export type.")
        return export_type


class MarkdownPreviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    presetKey: str = Field(default="summary_markdown")
    compact: bool = False
    visibleSections: list[str] = Field(default_factory=list)
    textOverrides: dict[str, str] = Field(default_factory=dict)


class GitHubProfileReadmeConnectPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    github_login: str = Field(min_length=1, max_length=255)
    profile_repo_owner: str = Field(min_length=1, max_length=255)
    profile_repo_name: str = Field(min_length=1, max_length=255)
    app_installation_id: int = Field(gt=0)


class GitHubProfileReadmeDiffPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_readme: str = Field(default="")
    presetKey: str = Field(default="profile_readme")
    compact: bool = True
    visibleSections: list[str] = Field(default_factory=list)
    textOverrides: dict[str, str] = Field(default_factory=dict)


class GitHubProfileReadmePublishPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_readme: str = Field(default="")
    confirm: bool = False
    presetKey: str = Field(default="profile_readme")
    compact: bool = True
    visibleSections: list[str] = Field(default_factory=list)
    textOverrides: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_confirm(self) -> "GitHubProfileReadmePublishPayload":
        if not self.confirm:
            raise ValueError("Explicit confirmation is required before publishing.")
        return self
