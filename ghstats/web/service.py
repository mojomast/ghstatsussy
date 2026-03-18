from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ghstats.web.config import WebAppSettings
from ghstats.web.crypto import TokenCipher
from ghstats.web.models import Report, ReportSnapshot, User
from ghstats.web.queue import enqueue_report_job
class HostedReportService:
    def __init__(self, settings: WebAppSettings, session: Session) -> None:
        self.settings = settings
        self.session = session
        self.cipher = TokenCipher(settings.secret_key)

    def encrypt_token(self, token: str) -> str:
        return self.cipher.encrypt(token)

    def decrypt_token(self, token: str) -> str:
        return self.cipher.decrypt(token)

    def create_or_update_user(
        self,
        *,
        github_user_id: int,
        login: str,
        name: str | None,
        avatar_url: str | None,
        profile_url: str | None,
        email: str | None,
        access_token: str,
        token_scopes: str,
    ) -> User:
        user = self.session.query(User).filter(User.github_user_id == github_user_id).one_or_none()
        if user is None:
            user = User(github_user_id=github_user_id, login=login, access_token_encrypted="")
            self.session.add(user)

        user.login = login
        user.name = name
        user.avatar_url = avatar_url
        user.profile_url = profile_url
        user.email = email
        user.access_token_encrypted = self.encrypt_token(access_token)
        user.token_scopes = token_scopes
        self.session.commit()
        self.session.refresh(user)
        return user

    def list_reports_for_user(self, user: User) -> list[Report]:
        return (
            self.session.query(Report)
            .filter(Report.user_id == user.id)
            .order_by(Report.updated_at.desc())
            .all()
        )

    def get_report_for_user(self, user: User, report_id: str) -> Report | None:
        return (
            self.session.query(Report)
            .filter(Report.id == report_id, Report.user_id == user.id)
            .one_or_none()
        )

    def get_report_by_slug(self, slug: str) -> Report | None:
        return self.session.query(Report).filter(Report.slug == slug).one_or_none()

    def get_report_by_username_host(self, username: str, slug: str | None = None) -> Report | None:
        query = self.session.query(Report).filter(
            Report.username_slug == username,
            Report.visibility != "private",
            Report.latest_snapshot_id.is_not(None),
        )
        if slug:
            query = query.filter(Report.slug == slug)
        return query.order_by(Report.generated_at.desc().nullslast()).first()

    def queue_report(
        self,
        *,
        user: User,
        since_spec: str,
        title: str | None,
        include_private: bool,
        visibility: str,
        store_metadata: bool,
        expires_in_days: int,
        sample_data: bool = False,
    ) -> Report:
        if visibility not in {"private", "unlisted", "public"}:
            raise ValueError("visibility must be private, unlisted, or public")
        if include_private and visibility != "private":
            raise ValueError("Reports with private activity must remain private in hosted mode.")
        if sample_data and not self.settings.allow_sample_reports:
            raise ValueError("Sample reports are disabled for this deployment.")

        use_metadata = store_metadata or self.settings.default_store_metadata or user.store_metadata_opt_in
        username_slug = self._normalize_username(user.login)

        report = Report(
            user_id=user.id,
            slug=self._generate_slug(),
            title=title or f"GitHub Activity - Last {since_spec}",
            since_spec=since_spec,
            include_private=include_private,
            visibility=visibility,
            status="queued",
            store_metadata=use_metadata,
            expires_at=_safe_expiry(days=expires_in_days),
            username_slug=username_slug,
        )
        self.session.add(report)
        self.session.flush()
        enqueue_report_job(
            self.session,
            report=report,
            job_type="generate",
            sample_data=sample_data,
        )
        self.session.commit()
        self.session.refresh(report)
        return report

    def queue_refresh(self, *, report: Report, sample_data: bool = False) -> Report:
        enqueue_report_job(
            self.session,
            report=report,
            job_type="refresh",
            sample_data=sample_data,
        )
        self.session.commit()
        self.session.refresh(report)
        return report

    def build_share_url(self, report: Report) -> str:
        return f"{self.settings.app_base_url}/r/{report.slug}"

    def build_host_url(self, report: Report) -> str | None:
        if report.username_slug is None:
            return None
        base = self.settings.ghstats_subdomain_base
        return f"https://{report.username_slug}.{base}/"

    def read_snapshot_html(self, snapshot: ReportSnapshot) -> str:
        return Path(snapshot.html_path).read_text(encoding="utf-8")

    def _generate_slug(self) -> str:
        while True:
            slug = secrets.token_urlsafe(8).replace("_", "").replace("-", "")[:12].lower()
            exists = self.session.query(Report).filter(Report.slug == slug).first()
            if exists is None:
                return slug

    def _normalize_username(self, value: str) -> str:
        username = value.strip().lower()
        username = "".join(char for char in username if char.isalnum() or char == "-")
        if not username:
            username = "report"
        if username in self.settings.reserved_report_usernames:
            username = f"u-{username}"
        return username


def serialize_report(report: Report, settings: WebAppSettings) -> dict[str, object]:
    host_url = None
    if report.username_slug:
        host_url = f"https://{report.username_slug}.{settings.ghstats_subdomain_base}/"
    return {
        "id": report.id,
        "slug": report.slug,
        "title": report.title,
        "since_spec": report.since_spec,
        "visibility": report.visibility,
        "include_private": report.include_private,
        "status": report.status,
        "generated_at": report.generated_at.isoformat() if report.generated_at else None,
        "share_url": f"{settings.app_base_url}/r/{report.slug}",
        "host_url": host_url,
        "store_metadata": report.store_metadata,
        "expires_at": report.expires_at.isoformat() if report.expires_at else None,
        "latest_job_id": report.latest_job_id,
    }


def _safe_expiry(*, days: int) -> datetime:
    clamped = max(1, min(days, 90))
    return datetime.now(timezone.utc) + timedelta(days=clamped)
