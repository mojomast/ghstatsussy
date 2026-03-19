from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ghstats.export.browser import (
    ExportRenderError,
    freeze_standalone_html,
    render_pdf,
    render_png,
)
from ghstats.export.markdown import build_markdown_export, render_markdown_preview
from ghstats.render.html import render_report_html
from ghstats.web.models import GitHubProfilePublishConnection, Report, ReportExport, ReportSnapshot, User
from ghstats.web.serialization import json_default


ALLOWED_EXPORT_TYPES = {"pdf", "png", "html", "markdown"}
ALLOWED_MARKDOWN_PRESETS = {"profile_readme", "summary_markdown"}


@dataclass(slots=True)
class ExportSource:
    report: Report
    snapshot: ReportSnapshot
    context: dict[str, Any]
    presentation_config: dict[str, Any]
    rendered_html: str
    snapshot_dir: Path


class ReportExportService:
    def __init__(self, settings: Any, session: Session) -> None:
        self.settings = settings
        self.session = session

    def list_exports_for_report(self, report: Report) -> list[ReportExport]:
        return (
            self.session.query(ReportExport)
            .filter(ReportExport.report_id == report.id)
            .order_by(ReportExport.created_at.desc())
            .all()
        )

    def get_export_for_user(self, user: User, report_id: str, export_id: str) -> ReportExport | None:
        return (
            self.session.query(ReportExport)
            .filter(
                ReportExport.id == export_id,
                ReportExport.report_id == report_id,
                ReportExport.owner_user_id == user.id,
            )
            .one_or_none()
        )

    def get_export_by_job(self, export_id: str | None) -> ReportExport | None:
        if not export_id:
            return None
        return self.session.get(ReportExport, export_id)

    def resolve_export_source(
        self,
        report: Report,
        snapshot: ReportSnapshot | None = None,
        *,
        presentation_config_override: dict[str, Any] | None = None,
    ) -> ExportSource:
        selected_snapshot = snapshot or report.latest_snapshot
        if selected_snapshot is None:
            raise ExportRenderError("Report snapshot is not ready yet.")
        snapshot_dir = self.settings.report_storage_dir / report.slug / f"v{selected_snapshot.version}"
        render_document_file = snapshot_dir / "render_document.json"
        if not render_document_file.exists():
            raise ExportRenderError("Stored render snapshot is missing; cannot build export.")
        context = json.loads(render_document_file.read_text(encoding="utf-8"))
        presentation_config = dict(presentation_config_override or report.presentation_config or {})
        template_key = str(presentation_config.get("themeKey") or report.template_key)
        rendered_html = render_report_html(
            context,
            template_key=template_key,
            presentation_config=presentation_config,
        )
        return ExportSource(
            report=report,
            snapshot=selected_snapshot,
            context=context,
            presentation_config=presentation_config,
            rendered_html=rendered_html,
            snapshot_dir=snapshot_dir,
        )

    def create_export_record(
        self,
        *,
        user: User,
        report: Report,
        export_type: str,
        options: dict[str, Any] | None = None,
    ) -> tuple[ReportExport, dict[str, Any]]:
        export_kind = export_type.strip().lower()
        if export_kind not in ALLOWED_EXPORT_TYPES:
            raise ValueError("Unsupported export type.")
        source = self.resolve_export_source(report)
        normalized_options = self._normalize_options(export_kind, options or {}, report)
        presentation_hash = self._hash_payload(source.presentation_config)
        options_hash = self._hash_payload(normalized_options)
        stored_options = self._with_internal_presentation_config(normalized_options, source.presentation_config)

        existing = (
            self.session.query(ReportExport)
            .filter(
                ReportExport.report_id == report.id,
                ReportExport.snapshot_id == source.snapshot.id,
                ReportExport.owner_user_id == user.id,
                ReportExport.export_type == export_kind,
                ReportExport.presentation_hash == presentation_hash,
                ReportExport.status == "succeeded",
            )
            .all()
        )
        for candidate in existing:
            if self._hash_payload(candidate.options_json or {}) == options_hash:
                return candidate, normalized_options

        export_record = ReportExport(
            report_id=report.id,
            snapshot_id=source.snapshot.id,
            owner_user_id=user.id,
            export_type=export_kind,
            status="queued",
            presentation_hash=presentation_hash,
            options_json=stored_options,
            expires_at=report.expires_at,
        )
        self.session.add(export_record)
        self.session.flush()
        return export_record, normalized_options

    def execute_export(self, export_record: ReportExport) -> ReportExport:
        report = self.session.get(Report, export_record.report_id)
        snapshot = self.session.get(ReportSnapshot, export_record.snapshot_id)
        if report is None or snapshot is None:
            raise ExportRenderError("Report export source no longer exists.")

        options = dict(export_record.options_json or {})
        presentation_override = self._internal_presentation_config(options)
        source = self.resolve_export_source(
            report,
            snapshot,
            presentation_config_override=presentation_override,
        )
        artifact_dir = source.snapshot_dir / "exports"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        binary_content: bytes | None = None
        text_content: str | None = None
        extension = ""
        mime_type = "application/octet-stream"

        if export_record.export_type == "pdf":
            avatar_source_url = source.context.get("meta", {}).get("subject", {}).get("avatar_url")
            binary_content = render_pdf(
                source.rendered_html,
                avatar_source_url=avatar_source_url,
            )
            extension = ".pdf"
            mime_type = "application/pdf"
        elif export_record.export_type == "png":
            avatar_source_url = source.context.get("meta", {}).get("subject", {}).get("avatar_url")
            binary_content = render_png(
                source.rendered_html,
                avatar_source_url=avatar_source_url,
            )
            extension = ".png"
            mime_type = "image/png"
        elif export_record.export_type == "html":
            avatar_source_url = source.context.get("meta", {}).get("subject", {}).get("avatar_url")
            text_content = freeze_standalone_html(
                source.rendered_html,
                avatar_source_url=avatar_source_url,
            )
            extension = ".html"
            mime_type = "text/html; charset=utf-8"
        elif export_record.export_type == "markdown":
            text_content = build_markdown_export(
                source.context,
                preset_key=str(options.get("presetKey", "summary_markdown")),
                options=options,
            )
            extension = ".md"
            mime_type = "text/markdown; charset=utf-8"
        else:  # pragma: no cover - guarded by validation
            raise ExportRenderError("Unsupported export type.")

        artifact_path = artifact_dir / f"{export_record.id}{extension}"
        if export_record.export_type in {"pdf", "png"}:
            if binary_content is None:
                raise ExportRenderError("Binary export content was not produced.")
            artifact_path.write_bytes(binary_content)
            byte_size = len(binary_content)
        else:
            if text_content is None:
                raise ExportRenderError("Text export content was not produced.")
            artifact_path.write_text(text_content, encoding="utf-8")
            byte_size = len(text_content.encode("utf-8"))

        export_record.artifact_path = str(artifact_path)
        export_record.mime_type = mime_type
        export_record.byte_size = byte_size
        export_record.status = "succeeded"
        export_record.error_message = None
        export_record.completed_at = _utcnow()
        export_record.expires_at = report.expires_at
        self.session.flush()
        return export_record

    def build_markdown_preview_html(self, report: Report, options: dict[str, Any] | None = None) -> str:
        return self.build_markdown_preview(report, options=options)["preview_html"]

    def build_markdown_preview(self, report: Report, options: dict[str, Any] | None = None) -> dict[str, str]:
        source = self.resolve_export_source(report)
        normalized_options = self._normalize_options("markdown", options or {}, report)
        markdown_body = build_markdown_export(
            source.context,
            preset_key=str(normalized_options.get("presetKey", "summary_markdown")),
            options=normalized_options,
        )
        return {
            "markdown": markdown_body,
            "preview_html": render_markdown_preview(markdown_body),
        }

    def build_markdown_for_profile_publish(self, report: Report, options: dict[str, Any] | None = None) -> dict[str, str]:
        merged_options = {"presetKey": "profile_readme", "compact": True}
        if options:
            merged_options.update(options)
        source = self.resolve_export_source(report)
        normalized_options = self._normalize_options("markdown", merged_options, report)
        markdown_body = build_markdown_export(
            source.context,
            preset_key="profile_readme",
            options=normalized_options,
        )
        return {
            "markdown": markdown_body,
            "preview_html": render_markdown_preview(markdown_body),
        }

    def get_profile_publish_status(self, user: User) -> dict[str, Any]:
        connection = self.session.get(GitHubProfilePublishConnection, user.id)
        expected_repo = f"{user.login}/{user.login}"
        return {
            "connected": connection is not None,
            "mode": "github_app_repo_install_only",
            "expected_repo": expected_repo,
            "connection": serialize_publish_connection(connection) if connection else None,
            "permissions_note": (
                "Install the GitHub App on the single profile repository only; do not use broad OAuth write scopes."
            ),
        }

    def connect_profile_publish_repo(
        self,
        *,
        user: User,
        github_login: str,
        profile_repo_owner: str,
        profile_repo_name: str,
        app_installation_id: int,
    ) -> GitHubProfilePublishConnection:
        if profile_repo_owner != user.login or profile_repo_name != user.login:
            raise ValueError("Profile publishing is limited to the exact username/username repository.")
        connection = self.session.get(GitHubProfilePublishConnection, user.id)
        if connection is None:
            connection = GitHubProfilePublishConnection(user_id=user.id, github_login=github_login, profile_repo_owner=profile_repo_owner, profile_repo_name=profile_repo_name, app_installation_id=app_installation_id)
            self.session.add(connection)
        else:
            connection.github_login = github_login
            connection.profile_repo_owner = profile_repo_owner
            connection.profile_repo_name = profile_repo_name
            connection.app_installation_id = app_installation_id
        self.session.flush()
        return connection

    def profile_readme_diff(self, report: Report, current_readme: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        preview = self.build_markdown_for_profile_publish(report, options=options)
        markdown_body = preview["markdown"]
        import difflib

        diff = "\n".join(
            difflib.unified_diff(
                current_readme.splitlines(),
                markdown_body.splitlines(),
                fromfile="current/README.md",
                tofile="generated/README.md",
                lineterm="",
            )
        )
        return {"markdown_body": markdown_body, "diff": diff}

    def record_publish_result(self, user: User, commit_sha: str) -> GitHubProfilePublishConnection | None:
        connection = self.session.get(GitHubProfilePublishConnection, user.id)
        if connection is None:
            return None
        connection.last_publish_commit_sha = commit_sha
        connection.last_publish_at = _utcnow()
        self.session.flush()
        return connection

    def _normalize_options(self, export_type: str, options: dict[str, Any], report: Report) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        if export_type == "markdown":
            preset = str(options.get("presetKey") or "summary_markdown").strip().lower()
            if preset not in ALLOWED_MARKDOWN_PRESETS:
                preset = "summary_markdown"
            normalized["presetKey"] = preset
            normalized["compact"] = bool(options.get("compact", preset == "profile_readme"))
            visible_sections = options.get("visibleSections")
            if isinstance(visible_sections, list):
                normalized["visibleSections"] = [str(item) for item in visible_sections if str(item).strip()]
            text_overrides = options.get("textOverrides")
            if isinstance(text_overrides, dict):
                normalized["textOverrides"] = {
                    str(key): " ".join(str(value).split())[:280]
                    for key, value in text_overrides.items()
                    if str(value).strip()
                }
            normalized["hostedReportUrl"] = self._build_hosted_report_url(report)
        return normalized

    def _build_hosted_report_url(self, report: Report) -> str:
        if self.settings.preview_mode:
            return f"/r/{report.slug}"
        return f"{self.settings.app_base_url}/r/{report.slug}"

    def _hash_payload(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=json_default)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _with_internal_presentation_config(
        self,
        options: dict[str, Any],
        presentation_config: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(options)
        merged["_presentationConfig"] = presentation_config
        return merged

    def _internal_presentation_config(self, options: dict[str, Any]) -> dict[str, Any] | None:
        raw = options.get("_presentationConfig")
        return dict(raw) if isinstance(raw, dict) else None


def serialize_export(export_record: ReportExport) -> dict[str, Any]:
    return {
        "id": export_record.id,
        "report_id": export_record.report_id,
        "snapshot_id": export_record.snapshot_id,
        "export_type": export_record.export_type,
        "status": export_record.status,
        "presentation_hash": export_record.presentation_hash,
        "options": _public_export_options(export_record.options_json or {}),
        "mime_type": export_record.mime_type,
        "byte_size": export_record.byte_size,
        "error_message": export_record.error_message,
        "created_at": export_record.created_at.isoformat() if export_record.created_at else None,
        "updated_at": export_record.updated_at.isoformat() if export_record.updated_at else None,
        "completed_at": export_record.completed_at.isoformat() if export_record.completed_at else None,
        "expires_at": export_record.expires_at.isoformat() if export_record.expires_at else None,
        "download_path": f"/api/reports/{export_record.report_id}/exports/{export_record.id}/download",
    }


def serialize_publish_connection(connection: GitHubProfilePublishConnection) -> dict[str, Any]:
    return {
        "github_login": connection.github_login,
        "profile_repo_owner": connection.profile_repo_owner,
        "profile_repo_name": connection.profile_repo_name,
        "app_installation_id": connection.app_installation_id,
        "last_publish_commit_sha": connection.last_publish_commit_sha,
        "last_publish_at": connection.last_publish_at.isoformat() if connection.last_publish_at else None,
    }


def _utcnow() -> Any:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _public_export_options(options: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in options.items()
        if not str(key).startswith("_")
    }
