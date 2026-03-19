from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ghstats.web.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    github_user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    login: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_token_encrypted: Mapped[str] = mapped_column(Text)
    token_scopes: Mapped[str] = mapped_column(Text, default="")
    store_metadata_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    can_use_public_subdomain: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    reports: Mapped[list[Report]] = relationship(back_populates="user", cascade="all, delete-orphan")
    profile_publish_connection: Mapped[GitHubProfilePublishConnection | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    since_spec: Mapped[str] = mapped_column(String(32))
    include_private: Mapped[bool] = mapped_column(Boolean, default=False)
    visibility: Mapped[str] = mapped_column(String(16), default="unlisted")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_snapshot_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("report_snapshots.id"), nullable=True)
    latest_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("report_jobs.id"), nullable=True)
    store_metadata: Mapped[bool] = mapped_column(Boolean, default=False)
    template_key: Mapped[str] = mapped_column(String(32), default="default")
    presentation_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    username_slug: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="reports", foreign_keys=[user_id])
    snapshots: Mapped[list[ReportSnapshot]] = relationship(
        back_populates="report",
        foreign_keys="ReportSnapshot.report_id",
        cascade="all, delete-orphan",
        order_by="ReportSnapshot.version",
    )
    jobs: Mapped[list[ReportJob]] = relationship(
        back_populates="report",
        foreign_keys="ReportJob.report_id",
        cascade="all, delete-orphan",
        order_by="ReportJob.created_at",
    )
    exports: Mapped[list[ReportExport]] = relationship(
        back_populates="report",
        foreign_keys="ReportExport.report_id",
        cascade="all, delete-orphan",
        order_by=lambda: ReportExport.created_at.desc(),
    )
    latest_snapshot: Mapped[ReportSnapshot | None] = relationship(
        foreign_keys=[latest_snapshot_id],
        post_update=True,
    )
    latest_job: Mapped[ReportJob | None] = relationship(
        foreign_keys=[latest_job_id],
        post_update=True,
    )


class ReportSnapshot(Base):
    __tablename__ = "report_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    report_id: Mapped[str] = mapped_column(String(36), ForeignKey("reports.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    html_path: Mapped[str] = mapped_column(Text)
    json_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    contains_private_data: Mapped[bool] = mapped_column(Boolean, default=False)
    restricted_contributions_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    report: Mapped[Report] = relationship(back_populates="snapshots", foreign_keys=[report_id])
    exports: Mapped[list[ReportExport]] = relationship(
        back_populates="snapshot",
        foreign_keys="ReportExport.snapshot_id",
        cascade="all, delete-orphan",
        order_by=lambda: ReportExport.created_at.desc(),
    )


class ReportExport(Base):
    __tablename__ = "report_exports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    report_id: Mapped[str] = mapped_column(String(36), ForeignKey("reports.id"), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(36), ForeignKey("report_snapshots.id"), index=True)
    owner_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    export_type: Mapped[str] = mapped_column(String(24), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    presentation_hash: Mapped[str] = mapped_column(String(64), index=True)
    options_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    report: Mapped[Report] = relationship(back_populates="exports", foreign_keys=[report_id])
    snapshot: Mapped[ReportSnapshot] = relationship(back_populates="exports", foreign_keys=[snapshot_id])


class GitHubProfilePublishConnection(Base):
    __tablename__ = "github_profile_publish_connections"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    github_login: Mapped[str] = mapped_column(String(255), index=True)
    profile_repo_owner: Mapped[str] = mapped_column(String(255))
    profile_repo_name: Mapped[str] = mapped_column(String(255))
    app_installation_id: Mapped[int] = mapped_column(Integer)
    last_publish_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="profile_publish_connection", foreign_keys=[user_id])


class ReportJob(Base):
    __tablename__ = "report_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    report_id: Mapped[str] = mapped_column(String(36), ForeignKey("reports.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    job_type: Mapped[str] = mapped_column(String(32), default="generate")
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    export_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_data: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    report: Mapped[Report] = relationship(back_populates="jobs", foreign_keys=[report_id])
