from __future__ import annotations

from pydantic import BaseModel, Field


class ReportCreatePayload(BaseModel):
    since_spec: str = Field(default="30d")
    title: str | None = None
    include_private: bool = False
    visibility: str = "unlisted"
    sample_data: bool = False
    store_metadata: bool = False
    expires_in_days: int = 14


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


class ViewerSummary(BaseModel):
    id: str
    login: str
    name: str | None
    avatar_url: str | None
    profile_url: str | None
    email: str | None
