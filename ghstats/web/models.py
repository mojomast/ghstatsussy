from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
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


class ReportJob(Base):
    __tablename__ = "report_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    report_id: Mapped[str] = mapped_column(String(36), ForeignKey("reports.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    job_type: Mapped[str] = mapped_column(String(16), default="generate")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_data: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    report: Mapped[Report] = relationship(back_populates="jobs", foreign_keys=[report_id])
