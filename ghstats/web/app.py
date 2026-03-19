from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import uvicorn
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ghstats.config import RuntimeConfig, StaticTokenProvider
from ghstats.export.browser import ExportRenderError
from ghstats.export.markdown import build_markdown_export, render_markdown_preview
from ghstats.export.service import serialize_export
from ghstats.render.html import render_report_html
from ghstats.render.templates import REPORT_TEMPLATES
from ghstats.render.themes import get_theme
from ghstats.service import GhStatsService
from ghstats.utils.timeparse import build_time_window
from ghstats.web.config import WebAppSettings, load_web_settings
from ghstats.web.database import Base, create_engine_and_session_factory
from ghstats.web.github_app import GitHubAppError, GitHubAppSettings, GitHubProfilePublisher
from ghstats.web.github_oauth import (
    GitHubOAuthError,
    build_authorize_url,
    exchange_code_for_token,
    fetch_github_user,
    generate_state,
)
from ghstats.web.jobs import process_next_job
from ghstats.web.models import Report, ReportJob, User
from ghstats.web.schemas import (
    ExportCreatePayload,
    GitHubProfileReadmeConnectPayload,
    GitHubProfileReadmeDiffPayload,
    GitHubProfileReadmePublishPayload,
    MarkdownPreviewPayload,
    ReportCreatePayload,
)
from ghstats.web.service import HostedReportService, serialize_report


TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
PREVIEW_READY_REPORT_ID = "11111111-1111-1111-1111-111111111111"
PREVIEW_RUNNING_REPORT_ID = "22222222-2222-2222-2222-222222222222"
PREVIEW_READY_JOB_ID = "33333333-3333-3333-3333-333333333333"
PREVIEW_RUNNING_JOB_ID = "44444444-4444-4444-4444-444444444444"
PREVIEW_INSTALLATION_ID = 424242

_PREVIEW_REPORTS_STATE: dict[str, dict] = {}
_PREVIEW_EXPORTS_STATE: dict[str, dict[str, dict[str, object]]] = {}
_PREVIEW_PROFILE_README_STATE: dict[str, object] = {
    "connected": False,
    "current_readme": "# Preview User\n\nA placeholder profile README in preview mode.\n",
    "last_publish_commit_sha": None,
}


def create_app(settings: WebAppSettings | None = None) -> FastAPI:
    web_settings = settings or load_web_settings()
    web_settings.report_storage_dir.mkdir(parents=True, exist_ok=True)
    engine, session_factory = create_engine_and_session_factory(web_settings.database_url)
    Base.metadata.create_all(bind=engine)

    app = FastAPI(title=web_settings.app_name)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=(
            ["*"]
            if web_settings.preview_mode
            else [
                "ghstats.ussyco.de",
                f"*.{web_settings.ghstats_subdomain_base}",
                "127.0.0.1",
                "localhost",
            ]
        ),
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=web_settings.secret_key,
        session_cookie=web_settings.session_cookie_name,
        https_only=web_settings.app_base_url.startswith("https://"),
        same_site="lax",
    )
    app.state.settings = web_settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    static_dir = web_settings.report_storage_dir / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "ghstatsussy-hosted"}

    @app.get("/gallery", response_class=HTMLResponse)
    def gallery(request: Request, user: User | None = Depends(optional_user)) -> HTMLResponse:
        if web_settings.preview_mode:
            reports = [report for report in _build_preview_reports(web_settings) if report["visibility"] == "public"]
        else:
            with session_factory() as session:
                service = HostedReportService(web_settings, session)
                reports = [serialize_report(report, web_settings) for report in service.list_public_reports()]
        return templates.TemplateResponse(
            request,
            "web/gallery.html.j2",
            {"settings": web_settings, "user": user, "reports": reports},
        )

    @app.get("/", response_class=HTMLResponse, response_model=None)
    def home(request: Request, user: User | None = Depends(optional_user)) -> HTMLResponse | RedirectResponse:
        if _is_report_host(request, web_settings):
            return _render_subdomain_report(request, web_settings, session_factory, user, report_path="")
        if user is not None and not web_settings.preview_mode:
            return RedirectResponse(url="/dashboard", status_code=302)
        return templates.TemplateResponse(request, "web/index.html.j2", {"settings": web_settings})

    @app.get("/auth/github/login")
    def github_login(request: Request) -> RedirectResponse:
        ensure_oauth_configured(web_settings)
        state = generate_state()
        request.session["github_oauth_state"] = state
        return RedirectResponse(build_authorize_url(web_settings, state), status_code=302)

    @app.get("/auth/github/callback")
    def github_callback(request: Request, code: str = "", state: str = "") -> RedirectResponse:
        expected_state = request.session.get("github_oauth_state")
        if not expected_state or state != expected_state:
            raise HTTPException(status_code=400, detail="OAuth state mismatch.")

        try:
            token_payload = exchange_code_for_token(web_settings, code)
            viewer = fetch_github_user(web_settings, token_payload["access_token"])
        except GitHubOAuthError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        with session_factory() as session:
            service = HostedReportService(web_settings, session)
            user = service.create_or_update_user(
                github_user_id=int(str(viewer["github_user_id"])),
                login=str(viewer["login"]),
                name=_none_or_str(viewer.get("name")),
                avatar_url=_none_or_str(viewer.get("avatar_url")),
                profile_url=_none_or_str(viewer.get("profile_url")),
                email=_none_or_str(viewer.get("email")),
                access_token=token_payload["access_token"],
                token_scopes=str(token_payload.get("scope", "")),
            )
            request.session["user_id"] = user.id

        request.session.pop("github_oauth_state", None)
        return RedirectResponse(url="/dashboard", status_code=302)

    @app.post("/auth/logout")
    def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse(url="/", status_code=302)

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request, user: User = Depends(require_user)) -> HTMLResponse:
        return _render_dashboard(request, web_settings, session_factory, user.id)

    @app.post("/dashboard/reports", response_model=None)
    def dashboard_create_report(
        request: Request,
        since_spec: str = Form("30d"),
        title: str = Form(""),
        include_private: str | None = Form(None),
        visibility: str = Form("unlisted"),
        expires_in_days: int = Form(14),
        store_metadata: str | None = Form(None),
        template_key: str = Form("default"),
        sample_data: str | None = Form(None),
        user: User = Depends(require_user),
    ) -> HTMLResponse | RedirectResponse:
        if web_settings.preview_mode:
            _PREVIEW_REPORTS_STATE[PREVIEW_READY_REPORT_ID] = {
                "themeKey": template_key,
                "visibleSections": [
                    "hero",
                    "profile_summary",
                    "key_stats",
                    "timeline_commits",
                    "timeline_loc",
                    "activity_heatmap",
                    "language_mix",
                    "language_breakdown",
                    "highlights",
                    "repositories",
                    "notes_and_warnings",
                    "footer_meta",
                ],
                "textOverrides": {},
            }
            return RedirectResponse(url=f"/dashboard/reports/{PREVIEW_READY_REPORT_ID}", status_code=302)

        form_values = _report_form_values(
            since_spec=since_spec,
            title=title,
            include_private=include_private,
            visibility=visibility,
            expires_in_days=expires_in_days,
            store_metadata=store_metadata,
            template_key=template_key,
            sample_data=sample_data,
        )
        try:
            payload = ReportCreatePayload.model_validate(
                {
                    "since_spec": since_spec,
                    "title": title or None,
                    "include_private": include_private == "true",
                    "visibility": visibility,
                    "sample_data": sample_data == "true",
                    "store_metadata": store_metadata == "true",
                    "expires_in_days": expires_in_days,
                    "template_key": template_key,
                }
            )
        except ValidationError as error:
            return _render_dashboard(
                request,
                web_settings,
                session_factory,
                user.id,
                status_code=400,
                form_error=_validation_message(error),
                form_values=form_values,
            )

        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            try:
                report = service.queue_report(
                    user=db_user,
                    since_spec=payload.since_spec,
                    title=payload.title,
                    include_private=payload.include_private,
                    visibility=payload.visibility,
                    store_metadata=payload.store_metadata,
                    expires_in_days=payload.expires_in_days,
                    template_key=payload.template_key,
                    sample_data=payload.sample_data,
                )
            except ValueError as error:
                session.rollback()
                return _render_dashboard(
                    request,
                    web_settings,
                    session_factory,
                    user.id,
                    status_code=400,
                    form_error=str(error),
                    form_values=form_values,
                )
            if web_settings.process_jobs_inline:
                process_next_job(web_settings, session)
        return RedirectResponse(url=f"/dashboard/reports/{report.id}", status_code=302)

    @app.get("/dashboard/reports/{report_id}", response_class=HTMLResponse)
    def dashboard_report_detail(request: Request, report_id: UUID, user: User = Depends(require_user)) -> HTMLResponse:
        if web_settings.preview_mode:
            report_data, snapshot = _preview_report_detail(web_settings, str(report_id))
            return templates.TemplateResponse(
                request,
                "web/report_detail.html.j2",
                {
                    "settings": web_settings,
                    "report": report_data,
                    "snapshot": snapshot,
                    "profile_publish_status": _preview_profile_publish_status(user),
                },
            )
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            report = service.get_report_for_user(db_user, str(report_id))
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found")
            snapshot = report.latest_snapshot
            report_data = serialize_report(report, web_settings)
            profile_publish_status = service.exports.get_profile_publish_status(db_user)
            profile_publish_status["install_url"] = _build_install_url_or_none(web_settings, db_user.login)
        return templates.TemplateResponse(
            request,
            "web/report_detail.html.j2",
            {
                "settings": web_settings,
                "report": report_data,
                "snapshot": snapshot,
                "profile_publish_status": profile_publish_status,
            },
        )

    @app.get("/api/me")
    def api_me(user: User = Depends(require_user)) -> dict[str, object]:
        return {
            "id": user.id,
            "login": user.login,
            "name": user.name,
            "avatar_url": user.avatar_url,
            "profile_url": user.profile_url,
            "email": user.email,
        }

    @app.get("/api/reports")
    def api_reports(user: User = Depends(require_user)) -> list[dict[str, object]]:
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            return [serialize_report(report, web_settings) for report in service.list_reports_for_user(db_user)]

    @app.post("/api/reports")
    def api_create_report(payload: ReportCreatePayload, user: User = Depends(require_user)) -> dict[str, object]:
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            try:
                report = service.queue_report(
                    user=db_user,
                    since_spec=payload.since_spec,
                    title=payload.title,
                    include_private=payload.include_private,
                    visibility=payload.visibility,
                    store_metadata=payload.store_metadata,
                    expires_in_days=payload.expires_in_days,
                    template_key=payload.template_key,
                    sample_data=payload.sample_data,
                )
            except ValueError as error:
                session.rollback()
                raise HTTPException(status_code=400, detail=str(error)) from error
            if web_settings.process_jobs_inline:
                process_next_job(web_settings, session)
            return serialize_report(report, web_settings)

    @app.get("/api/reports/{report_id}")
    def api_report_detail(report_id: UUID, user: User = Depends(require_user)) -> dict[str, object]:
        if web_settings.preview_mode:
            report_data, _ = _preview_report_detail(web_settings, str(report_id))
            return report_data
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            report = service.get_report_for_user(db_user, str(report_id))
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found")
            payload = serialize_report(report, web_settings)
            payload["latest_snapshot_id"] = report.latest_snapshot_id
            payload["error_message"] = report.error_message
            return payload

    @app.post("/api/reports/{report_id}/presentation")
    def api_update_presentation(report_id: UUID, payload: dict, user: User = Depends(require_user)) -> dict[str, object]:
        if web_settings.preview_mode:
            rid = str(report_id)
            config = dict(_PREVIEW_REPORTS_STATE.get(rid, {}))
            config = _merge_presentation_payload(config, payload)
            _PREVIEW_REPORTS_STATE[rid] = config
            return {"status": "ok", "presentation_config": config}
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            report = service.get_report_for_user(db_user, str(report_id))
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found")
            existing_config = getattr(report, "presentation_config", None)
            config = dict(existing_config) if existing_config else {}
            config = _merge_presentation_payload(config, payload)
            if "themeKey" in config:
                report.template_key = str(config["themeKey"])
            report.presentation_config = config
            session.commit()
            return {"status": "ok", "presentation_config": config}

    @app.post("/dashboard/reports/{report_id}/refresh")
    def dashboard_refresh_report(report_id: UUID, user: User = Depends(require_user)) -> RedirectResponse:
        if web_settings.preview_mode:
            return RedirectResponse(url=f"/dashboard/reports/{report_id}", status_code=302)
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            report = service.get_report_for_user(db_user, str(report_id))
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found")
            service.queue_refresh(report=report, sample_data=False)
            if web_settings.process_jobs_inline:
                process_next_job(web_settings, session)
        return RedirectResponse(url=f"/dashboard/reports/{report_id}", status_code=302)

    @app.post("/api/reports/{report_id}/refresh")
    def api_refresh_report(
        report_id: UUID,
        payload: ReportCreatePayload | None = None,
        user: User = Depends(require_user),
    ) -> dict[str, object]:
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            report = service.get_report_for_user(db_user, str(report_id))
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found")
            report = service.queue_refresh(report=report, sample_data=payload.sample_data if payload else False)
            if web_settings.process_jobs_inline:
                process_next_job(web_settings, session)
            return serialize_report(report, web_settings)

    @app.post("/api/reports/{report_id}/exports")
    def api_create_export(
        report_id: UUID,
        payload: ExportCreatePayload,
        user: User = Depends(require_user),
    ) -> dict[str, object]:
        if web_settings.preview_mode:
            export_entry = _preview_create_export(web_settings, str(report_id), payload.exportType, payload.options)
            return export_entry
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            report = service.get_report_for_user(db_user, str(report_id))
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found")
            try:
                export_record = service.queue_export(
                    user=db_user,
                    report=report,
                    export_type=payload.exportType,
                    options=payload.options,
                )
            except (ValueError, ExportRenderError) as error:
                session.rollback()
                raise HTTPException(status_code=400, detail=str(error)) from error
            if web_settings.process_jobs_inline:
                process_next_job(web_settings, session)
                session.refresh(export_record)
            return serialize_export(export_record)

    @app.get("/api/reports/{report_id}/exports")
    def api_list_exports(report_id: UUID, user: User = Depends(require_user)) -> list[dict[str, object]]:
        if web_settings.preview_mode:
            return _preview_list_exports(str(report_id))
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            report = service.get_report_for_user(db_user, str(report_id))
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found")
            return [serialize_export(export_record) for export_record in service.list_exports(report)]

    @app.get("/api/reports/{report_id}/exports/{export_id}")
    def api_export_detail(report_id: UUID, export_id: UUID, user: User = Depends(require_user)) -> dict[str, object]:
        if web_settings.preview_mode:
            export_entry = _preview_get_export(str(report_id), str(export_id))
            if export_entry is None:
                raise HTTPException(status_code=404, detail="Export not found")
            return export_entry
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            report = service.get_report_for_user(db_user, str(report_id))
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found")
            export_record = service.get_export_for_user(db_user, report, str(export_id))
            if export_record is None:
                raise HTTPException(status_code=404, detail="Export not found")
            return serialize_export(export_record)

    @app.get("/api/reports/{report_id}/exports/{export_id}/download")
    def api_export_download(report_id: UUID, export_id: UUID, user: User = Depends(require_user)):
        if web_settings.preview_mode:
            export_entry = _preview_get_export(str(report_id), str(export_id))
            if export_entry is None:
                raise HTTPException(status_code=404, detail="Export not found")
            return _preview_download_export(web_settings, str(report_id), export_entry)
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            report = service.get_report_for_user(db_user, str(report_id))
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found")
            export_record = service.get_export_for_user(db_user, report, str(export_id))
            if export_record is None or not export_record.artifact_path:
                raise HTTPException(status_code=404, detail="Export artifact not found")
            artifact_path = Path(export_record.artifact_path)
            if not artifact_path.exists():
                raise HTTPException(status_code=404, detail="Export artifact file is missing")
            filename = f"{_safe_filename(report.title)}-{export_record.export_type}{artifact_path.suffix}"
            return FileResponse(path=artifact_path, media_type=export_record.mime_type, filename=filename)

    @app.get("/api/reports/{report_id}/markdown")
    def api_markdown_detail(report_id: UUID, user: User = Depends(require_user)) -> dict[str, object]:
        options = {"presetKey": "summary_markdown", "compact": False}
        if web_settings.preview_mode:
            preview = _preview_markdown_preview(web_settings, str(report_id), options)
            return {"presetKey": options["presetKey"], **preview}
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            report = service.get_report_for_user(db_user, str(report_id))
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found")
            preview = service.exports.build_markdown_preview(report, options=options)
            return {"presetKey": options["presetKey"], **preview}

    @app.post("/api/reports/{report_id}/markdown")
    def api_markdown_generate(
        report_id: UUID,
        payload: MarkdownPreviewPayload,
        user: User = Depends(require_user),
    ) -> dict[str, object]:
        options = payload.model_dump()
        if web_settings.preview_mode:
            preview = _preview_markdown_preview(web_settings, str(report_id), options)
            return {"presetKey": options.get("presetKey", "summary_markdown"), **preview}
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            report = service.get_report_for_user(db_user, str(report_id))
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found")
            preview = service.exports.build_markdown_preview(report, options=options)
            return {"presetKey": options.get("presetKey", "summary_markdown"), **preview}

    @app.post("/api/reports/{report_id}/markdown/preview")
    def api_markdown_preview(
        report_id: UUID,
        payload: MarkdownPreviewPayload,
        user: User = Depends(require_user),
    ) -> dict[str, object]:
        return api_markdown_generate(report_id, payload, user)

    @app.get("/api/github/profile-readme/status")
    def api_profile_readme_status(user: User = Depends(require_user)) -> dict[str, object]:
        if web_settings.preview_mode:
            return _preview_profile_publish_status(user)
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            status = service.exports.get_profile_publish_status(db_user)
            status["install_url"] = _build_install_url_or_none(web_settings, db_user.login)
            return status

    @app.post("/api/github/profile-readme/connect")
    def api_profile_readme_connect(
        payload: GitHubProfileReadmeConnectPayload,
        user: User = Depends(require_user),
    ) -> dict[str, object]:
        if web_settings.preview_mode:
            _PREVIEW_PROFILE_README_STATE["connected"] = True
            return _preview_profile_publish_status(user)
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            try:
                publisher = _build_profile_publisher(web_settings)
                publisher.verify_profile_repo_installation(
                    installation_id=payload.app_installation_id,
                    owner=payload.profile_repo_owner,
                    repo=payload.profile_repo_name,
                )
                service.exports.connect_profile_publish_repo(
                    user=db_user,
                    github_login=payload.github_login,
                    profile_repo_owner=payload.profile_repo_owner,
                    profile_repo_name=payload.profile_repo_name,
                    app_installation_id=payload.app_installation_id,
                )
            except (ValueError, GitHubAppError, Exception) as error:
                session.rollback()
                raise HTTPException(status_code=400, detail=str(error)) from error
            session.commit()
            status = service.exports.get_profile_publish_status(db_user)
            status["install_url"] = _build_install_url_or_none(web_settings, db_user.login)
            return status

    @app.get("/api/github/profile-readme/current")
    def api_profile_readme_current(user: User = Depends(require_user)) -> dict[str, object]:
        if web_settings.preview_mode:
            return {
                "exists": True,
                "content": str(_PREVIEW_PROFILE_README_STATE["current_readme"]),
                "sha": str(_PREVIEW_PROFILE_README_STATE.get("last_publish_commit_sha") or "preview-sha"),
            }
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            status = service.exports.get_profile_publish_status(db_user)
            connection = status.get("connection")
            if not connection:
                raise HTTPException(status_code=400, detail="GitHub App repo connection is not configured.")
            publisher = _build_profile_publisher(web_settings)
            try:
                return publisher.fetch_current_readme(
                    installation_id=int(connection["app_installation_id"]),
                    owner=str(connection["profile_repo_owner"]),
                    repo=str(connection["profile_repo_name"]),
                )
            except (GitHubAppError, Exception) as error:
                raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/reports/{report_id}/profile-readme/diff")
    def api_profile_readme_diff(
        report_id: UUID,
        payload: GitHubProfileReadmeDiffPayload,
        user: User = Depends(require_user),
    ) -> dict[str, object]:
        options = payload.model_dump(exclude={"current_readme"})
        if web_settings.preview_mode:
            preview = _preview_markdown_preview(web_settings, str(report_id), options)
            markdown_body = str(preview["markdown"])
            preview_html = str(preview["preview_html"])
            return {
                "markdown_body": markdown_body,
                "preview_html": preview_html,
                "diff": _unified_diff(payload.current_readme, markdown_body),
            }
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            report = service.get_report_for_user(db_user, str(report_id))
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found")
            preview_payload = service.exports.build_markdown_for_profile_publish(report, options=options)
            diff_payload = service.exports.profile_readme_diff(report, payload.current_readme, options=options)
            diff_payload["preview_html"] = preview_payload["preview_html"]
            return diff_payload

    @app.post("/api/reports/{report_id}/profile-readme/publish")
    def api_profile_readme_publish(
        report_id: UUID,
        payload: GitHubProfileReadmePublishPayload,
        user: User = Depends(require_user),
    ) -> dict[str, object]:
        options = payload.model_dump(exclude={"current_readme", "confirm"})
        if web_settings.preview_mode:
            preview = _preview_markdown_preview(web_settings, str(report_id), options)
            markdown_body = str(preview["markdown"])
            _PREVIEW_PROFILE_README_STATE["current_readme"] = markdown_body
            _PREVIEW_PROFILE_README_STATE["last_publish_commit_sha"] = "preview-commit-sha"
            return {
                "status": "published",
                "commit_sha": "preview-commit-sha",
                "markdown_body": markdown_body,
                "diff": _unified_diff(payload.current_readme, markdown_body),
            }
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            report = service.get_report_for_user(db_user, str(report_id))
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found")
            status = service.exports.get_profile_publish_status(db_user)
            connection = status.get("connection")
            if not connection:
                raise HTTPException(status_code=400, detail="GitHub App repo connection is not configured.")
            publisher = _build_profile_publisher(web_settings)
            try:
                current = publisher.fetch_current_readme(
                    installation_id=int(connection["app_installation_id"]),
                    owner=str(connection["profile_repo_owner"]),
                    repo=str(connection["profile_repo_name"]),
                )
                preview_payload = service.exports.build_markdown_for_profile_publish(report, options=options)
                diff_payload = service.exports.profile_readme_diff(report, str(current.get("content") or ""), options=options)
                commit_sha = publisher.publish_readme(
                    installation_id=int(connection["app_installation_id"]),
                    owner=str(connection["profile_repo_owner"]),
                    repo=str(connection["profile_repo_name"]),
                    markdown_body=preview_payload["markdown"],
                    sha=_none_or_str(current.get("sha")),
                    commit_message="Update profile README from ghstatsussy snapshot",
                )
                service.exports.record_publish_result(db_user, commit_sha)
                session.commit()
                return {
                    "status": "published",
                    "commit_sha": commit_sha,
                    "markdown_body": preview_payload["markdown"],
                    "diff": diff_payload["diff"],
                }
            except (GitHubAppError, Exception) as error:
                session.rollback()
                raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/jobs/{job_id}")
    def api_job_detail(job_id: UUID, user: User = Depends(require_user)) -> dict[str, object]:
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            job = (
                session.query(ReportJob)
                .join(Report, Report.id == ReportJob.report_id)
                .filter(Report.user_id == db_user.id, ReportJob.id == str(job_id))
                .one_or_none()
            )
            if job is None:
                raise HTTPException(status_code=404, detail="Job not found")
            progress_percent, current_step, total_steps = _job_progress(job.status)
            return {
                "id": job.id,
                "report_id": job.report_id,
                "status": job.status,
                "job_type": job.job_type,
                "export_id": job.export_id,
                "error_message": job.error_message,
                "created_at": job.created_at.isoformat(),
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                "progress_percent": progress_percent,
                "current_step": current_step,
                "total_steps": total_steps,
            }

    @app.get("/dashboard/reports/{report_id}/progress", response_class=HTMLResponse)
    def dashboard_report_progress_partial(report_id: UUID, request: Request, user: User = Depends(require_user)) -> HTMLResponse:
        if web_settings.preview_mode:
            report_data, _ = _preview_report_detail(web_settings, str(report_id))
            progress_percent, current_step, total_steps = _job_progress(str(report_data["status"]))
            context = {
                "report": report_data,
                "job": _preview_job(report_data),
                "progress_percent": progress_percent,
                "current_step": current_step,
                "total_steps": total_steps,
            }
            return templates.TemplateResponse(request, "web/_report_progress.html.j2", context)
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            report = service.get_report_for_user(db_user, str(report_id))
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found")
            job = report.latest_job
            progress_percent, current_step, total_steps = _job_progress(job.status if job else report.status)
            context = {
                "report": serialize_report(report, web_settings),
                "job": job,
                "progress_percent": progress_percent,
                "current_step": current_step,
                "total_steps": total_steps,
            }
        return templates.TemplateResponse(request, "web/_report_progress.html.j2", context)

    @app.get("/r/{slug}")
    def public_report(slug: str, request: Request, user: User | None = Depends(optional_user)) -> HTMLResponse:
        if web_settings.preview_mode and slug == "preview-ready-report":
            artifacts = _preview_artifacts(web_settings, PREVIEW_READY_REPORT_ID)
            return HTMLResponse(content=artifacts["html"])

        with session_factory() as session:
            service = HostedReportService(web_settings, session)
            report = service.get_report_by_slug(slug)
            if report is None or report.latest_snapshot is None:
                raise HTTPException(status_code=404, detail="Report not found")
            if report.visibility == "private":
                if user is None or user.id != report.user_id:
                    raise HTTPException(status_code=403, detail="This report is private.")
            html = service.read_snapshot_html(report.latest_snapshot)
        return HTMLResponse(content=html)

    @app.get("/{report_path:path}", response_class=HTMLResponse, response_model=None)
    def subdomain_report(request: Request, report_path: str, user: User | None = Depends(optional_user)) -> HTMLResponse:
        return _render_subdomain_report(request, web_settings, session_factory, user, report_path=report_path)

    return app


def optional_user(request: Request) -> User | None:
    settings: WebAppSettings = request.app.state.settings
    if settings.preview_mode:
        return _preview_user(settings)
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        return session.get(User, user_id)


def require_user(request: Request) -> User:
    user = optional_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in with GitHub first.")
    return user


def ensure_oauth_configured(settings: WebAppSettings) -> None:
    if not settings.github_client_id or not settings.github_client_secret:
        raise HTTPException(
            status_code=500,
            detail="GitHub OAuth is not configured. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET.",
        )


def _render_dashboard(
    request: Request,
    settings: WebAppSettings,
    session_factory: sessionmaker[Session],
    user_id: str,
    *,
    status_code: int = 200,
    form_error: str | None = None,
    form_values: dict[str, object] | None = None,
) -> HTMLResponse:
    if settings.preview_mode and user_id == "preview-user":
        preview_user = _preview_user(settings)
        context = {
            "settings": settings,
            "user": preview_user,
            "reports": _build_preview_reports(settings),
            "allow_sample_reports": True,
            "report_templates": REPORT_TEMPLATES,
            "get_report_theme": get_theme,
            "form_error": form_error,
            "form_values": _merged_report_form_values(settings, form_values),
        }
        return templates.TemplateResponse(request, "web/dashboard.html.j2", context, status_code=status_code)

    with session_factory() as session:
        db_user = session.get(User, user_id)
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")
        service = HostedReportService(settings, session)
        reports = [serialize_report(report, settings) for report in service.list_reports_for_user(db_user)]
        context = {
            "settings": settings,
            "user": db_user,
            "reports": reports,
            "allow_sample_reports": settings.allow_sample_reports,
            "report_templates": REPORT_TEMPLATES,
            "get_report_theme": get_theme,
            "form_error": form_error,
            "form_values": _merged_report_form_values(settings, form_values),
        }
    return templates.TemplateResponse(request, "web/dashboard.html.j2", context, status_code=status_code)


def _merged_report_form_values(settings: WebAppSettings, form_values: dict[str, object] | None) -> dict[str, object]:
    default_expiry = settings.default_report_expiry_days
    if settings.default_visibility == "public":
        default_expiry = min(default_expiry, 30)
    values = {
        "since_spec": "30d",
        "title": "",
        "include_private": False,
        "visibility": settings.default_visibility,
        "expires_in_days": str(default_expiry),
        "store_metadata": False,
        "template_key": REPORT_TEMPLATES[0].key,
        "sample_data": False,
    }
    if form_values:
        values.update(form_values)
    return values


def _report_form_values(
    *,
    since_spec: str,
    title: str,
    include_private: str | None,
    visibility: str,
    expires_in_days: int,
    store_metadata: str | None,
    template_key: str,
    sample_data: str | None,
) -> dict[str, object]:
    return {
        "since_spec": since_spec,
        "title": title,
        "include_private": include_private == "true",
        "visibility": visibility,
        "expires_in_days": str(expires_in_days),
        "store_metadata": store_metadata == "true",
        "template_key": template_key,
        "sample_data": sample_data == "true",
    }


def _validation_message(error: ValidationError) -> str:
    errors = error.errors(include_url=False)
    if not errors:
        return "Invalid report settings."
    message = str(errors[0].get("msg", "Invalid report settings."))
    prefix = "Value error, "
    if message.startswith(prefix):
        return message[len(prefix):]
    return message


def _build_preview_reports(settings: WebAppSettings) -> list[dict[str, object]]:
    base_url = "" if settings.preview_mode else settings.app_base_url.rstrip("/")
    login = settings.preview_user_login
    ready_config = _PREVIEW_REPORTS_STATE.get(PREVIEW_READY_REPORT_ID, {})
    ready_template = ready_config.get("themeKey", "orbital")

    return [
        {
            "id": PREVIEW_READY_REPORT_ID,
            "slug": "preview-ready-report",
            "title": "Release Drift / Last 30d",
            "since_spec": "30d",
            "visibility": "public",
            "include_private": False,
            "status": "ready",
            "generated_at": "2026-03-18T20:45:00+00:00",
            "share_url": f"{base_url}/r/preview-ready-report",
            "host_url": f"https://{login}.preview.local/",
            "store_metadata": True,
            "template_key": ready_template,
            "presentation_config": ready_config,
            "latest_job_id": PREVIEW_READY_JOB_ID,
            "expires_at": "2026-04-17T20:45:00+00:00",
            "exports": _preview_list_exports(PREVIEW_READY_REPORT_ID),
            "user": {"login": login, "avatar_url": None},
        },
        {
            "id": PREVIEW_RUNNING_REPORT_ID,
            "slug": "preview-running-report",
            "title": "Gallery Pulse / Last 90d",
            "since_spec": "90d",
            "visibility": "unlisted",
            "include_private": False,
            "status": "running",
            "generated_at": None,
            "share_url": f"{base_url}/r/preview-running-report",
            "host_url": None,
            "store_metadata": False,
            "template_key": "gallery",
            "latest_job_id": PREVIEW_RUNNING_JOB_ID,
            "expires_at": "2026-04-30T19:00:00+00:00",
            "exports": [],
            "user": {"login": login, "avatar_url": None},
        },
    ]


def _preview_report_detail(settings: WebAppSettings, report_id: str) -> tuple[dict[str, object], dict[str, object] | None]:
    reports = {report["id"]: report for report in _build_preview_reports(settings)}
    report = reports.get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    snapshot: dict[str, object] | None = None
    if report["status"] == "ready":
        snapshot = {"version": int(3)}
    return report, snapshot


def _preview_job(report: dict[str, object]) -> dict[str, object] | None:
    status = str(report["status"])
    if status == "ready":
        return {
            "id": PREVIEW_READY_JOB_ID,
            "status": "succeeded",
            "created_at": "2026-03-18T20:30:00+00:00",
            "started_at": "2026-03-18T20:31:00+00:00",
            "finished_at": "2026-03-18T20:45:00+00:00",
        }
    if status == "running":
        return {
            "id": PREVIEW_RUNNING_JOB_ID,
            "status": "running",
            "created_at": "2026-03-18T21:00:00+00:00",
            "started_at": "2026-03-18T21:01:00+00:00",
            "finished_at": None,
        }
    return None


def _preview_user(settings: WebAppSettings) -> User:
    user = User(github_user_id=0, login=settings.preview_user_login, access_token_encrypted="preview-token")
    user.id = "preview-user"
    user.name = settings.preview_user_name
    user.avatar_url = None
    user.profile_url = None
    user.email = None
    user.store_metadata_opt_in = False
    user.can_use_public_subdomain = True
    return user


def _preview_artifacts(settings: WebAppSettings, report_id: str) -> dict[str, Any]:
    report_state = _PREVIEW_REPORTS_STATE.get(report_id, {})
    template_key = str(report_state.get("themeKey") or "orbital")
    presentation_config = dict(report_state or {"themeKey": template_key})
    service = GhStatsService(RuntimeConfig(include_private=False, token_provider=StaticTokenProvider("dummy")))
    artifacts = service.build_artifacts(
        window=build_time_window("30d"),
        sample_data=True,
        template_key=template_key,
        presentation_config=presentation_config,
    )
    html_document = render_report_html(
        artifacts.context,
        template_key=template_key,
        presentation_config=presentation_config,
    )
    return {
        "context": artifacts.context,
        "html": html_document,
        "presentation_config": presentation_config,
    }


def _preview_create_export(settings: WebAppSettings, report_id: str, export_type: str, options: dict) -> dict[str, object]:
    report_data, _ = _preview_report_detail(settings, report_id)
    export_id = str(uuid4())
    mime_map = {
        "pdf": "application/pdf",
        "png": "image/png",
        "html": "text/html; charset=utf-8",
        "markdown": "text/markdown; charset=utf-8",
    }
    entry = {
        "id": export_id,
        "report_id": report_id,
        "snapshot_id": "preview-snapshot-v3",
        "export_type": export_type,
        "status": "succeeded",
        "presentation_hash": "preview",
        "options": options,
        "mime_type": mime_map.get(export_type, "application/octet-stream"),
        "byte_size": None,
        "error_message": None,
        "created_at": "2026-03-19T00:00:00+00:00",
        "updated_at": "2026-03-19T00:00:00+00:00",
        "completed_at": "2026-03-19T00:00:00+00:00",
        "expires_at": report_data.get("expires_at"),
        "download_path": f"/api/reports/{report_id}/exports/{export_id}/download",
    }
    _PREVIEW_EXPORTS_STATE.setdefault(report_id, {})[export_id] = entry
    return entry


def _preview_list_exports(report_id: str) -> list[dict[str, object]]:
    exports = list(_PREVIEW_EXPORTS_STATE.get(report_id, {}).values())
    return sorted(exports, key=lambda item: str(item.get("created_at", "")), reverse=True)


def _preview_get_export(report_id: str, export_id: str) -> dict[str, object] | None:
    return _PREVIEW_EXPORTS_STATE.get(report_id, {}).get(export_id)


def _preview_markdown_preview(settings: WebAppSettings, report_id: str, options: dict[str, object]) -> dict[str, object]:
    preview = _preview_artifacts(settings, report_id)
    context = preview["context"]
    markdown_body = build_markdown_export(
        context,
        preset_key=str(options.get("presetKey", "summary_markdown")),
        options=dict(options),
    )
    return {"markdown": markdown_body, "preview_html": render_markdown_preview(markdown_body)}


def _preview_download_export(settings: WebAppSettings, report_id: str, export_entry: dict[str, object]):
    preview = _preview_artifacts(settings, report_id)
    export_type = str(export_entry["export_type"])
    if export_type == "markdown":
        options_raw = export_entry.get("options")
        options: dict[str, object] = dict(options_raw) if isinstance(options_raw, dict) else {}
        markdown_body = build_markdown_export(
            preview["context"],
            preset_key=str(options.get("presetKey", "summary_markdown")),
            options=options,
        )
        return PlainTextResponse(markdown_body, media_type="text/markdown")
    if export_type == "html":
        return HTMLResponse(str(preview["html"]))
    return PlainTextResponse(
        f"Preview mode stub for {export_type} export. Use the real hosted flow for binary artifact generation.",
        media_type="text/plain",
    )


def _preview_profile_publish_status(user: User) -> dict[str, object]:
    connected = bool(_PREVIEW_PROFILE_README_STATE["connected"])
    return {
        "connected": connected,
        "mode": "github_app_repo_install_only",
        "expected_repo": f"{user.login}/{user.login}",
        "install_url": "https://github.com/apps/example-ghstats/installations/new",
        "permissions_note": "Preview mode mirrors the production safety model: GitHub App install on one profile repo only.",
        "connection": {
            "github_login": user.login,
            "profile_repo_owner": user.login,
            "profile_repo_name": user.login,
            "app_installation_id": PREVIEW_INSTALLATION_ID,
            "last_publish_commit_sha": _PREVIEW_PROFILE_README_STATE.get("last_publish_commit_sha"),
            "last_publish_at": "2026-03-19T00:00:00+00:00" if _PREVIEW_PROFILE_README_STATE.get("last_publish_commit_sha") else None,
        } if connected else None,
    }


def _none_or_str(value: object | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _job_progress(status: str) -> tuple[int, int, int]:
    mapping = {
        "queued": (28, 2, 4),
        "running": (68, 3, 4),
        "succeeded": (100, 4, 4),
        "ready": (100, 4, 4),
        "failed": (100, 4, 4),
    }
    return mapping.get(status, (14, 1, 4))


def _is_report_host(request: Request, settings: WebAppSettings) -> bool:
    host = request.headers.get("host", "").split(":", 1)[0].lower()
    suffix = f".{settings.ghstats_subdomain_base}"
    return host.endswith(suffix)


def _render_subdomain_report(
    request: Request,
    settings: WebAppSettings,
    session_factory: sessionmaker[Session],
    user: User | None,
    *,
    report_path: str,
) -> HTMLResponse:
    host = request.headers.get("host", "").split(":", 1)[0].lower()
    suffix = f".{settings.ghstats_subdomain_base}"
    if not host.endswith(suffix):
        raise HTTPException(status_code=404, detail="Report not found")
    username = host[: -len(suffix)]
    if not username:
        raise HTTPException(status_code=404, detail="Report not found")

    slug = report_path.strip("/") or None
    with session_factory() as session:
        service = HostedReportService(settings, session)
        report = service.get_report_by_username_host(username=username, slug=slug)
        if report is None or report.latest_snapshot is None:
            raise HTTPException(status_code=404, detail="Report not found")
        html_document = service.read_snapshot_html(report.latest_snapshot)
    return HTMLResponse(content=html_document)


def _merge_presentation_payload(existing: dict[str, object], payload: dict[str, object]) -> dict[str, object]:
    config = dict(existing)
    if "themeKey" in payload:
        theme_key = str(payload["themeKey"]).strip().lower()
        valid_template_keys = {template.key for template in REPORT_TEMPLATES}
        if theme_key not in valid_template_keys:
            raise HTTPException(status_code=400, detail="Invalid report theme.")
        config["themeKey"] = theme_key
    visible_sections = payload.get("visibleSections")
    if isinstance(visible_sections, list):
        allowed_sections = {
            "hero",
            "profile_summary",
            "key_stats",
            "timeline_commits",
            "timeline_loc",
            "activity_heatmap",
            "language_mix",
            "language_breakdown",
            "highlights",
            "repositories",
            "notes_and_warnings",
            "footer_meta",
        }
        normalized_sections: list[str] = []
        for item in visible_sections:
            section = str(item).strip()
            if section in allowed_sections and section not in normalized_sections:
                normalized_sections.append(section)
        config["visibleSections"] = normalized_sections
    text_overrides = payload.get("textOverrides")
    if isinstance(text_overrides, dict):
        config["textOverrides"] = {
            str(key): str(value)[:280]
            for key, value in text_overrides.items()
            if isinstance(value, str)
        }
    return config


def _build_profile_publisher(settings: WebAppSettings) -> GitHubProfilePublisher:
    if not settings.github_app_id or not settings.github_app_private_key or not settings.github_app_slug:
        raise GitHubAppError(
            "GitHub App publishing is not configured. Set GITHUB_APP_ID, GITHUB_APP_SLUG, and GITHUB_APP_PRIVATE_KEY."
        )
    app_settings = GitHubAppSettings(
        app_id=settings.github_app_id,
        private_key=settings.github_app_private_key,
        app_slug=settings.github_app_slug,
        api_url=settings.github_app_api_url,
        app_url=settings.github_app_base_url,
    )
    return GitHubProfilePublisher(app_settings)


def _build_install_url_or_none(settings: WebAppSettings, login: str) -> str | None:
    try:
        return _build_profile_publisher(settings).build_install_url(login, login)
    except GitHubAppError:
        return None


def _unified_diff(current_readme: str, markdown_body: str) -> str:
    import difflib

    return "\n".join(
        difflib.unified_diff(
            current_readme.splitlines(),
            markdown_body.splitlines(),
            fromfile="current/README.md",
            tofile="generated/README.md",
            lineterm="",
        )
    )


def _safe_filename(value: str) -> str:
    collapsed = "-".join(part for part in value.lower().split() if part)
    return "".join(char for char in collapsed if char.isalnum() or char in {"-", "_"}) or "report"


app = create_app()


def run() -> None:
    settings = load_web_settings()
    uvicorn.run(
        "ghstats.web.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
    )
