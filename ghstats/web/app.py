from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from ghstats.web.config import WebAppSettings, load_web_settings
from ghstats.web.database import Base, create_engine_and_session_factory
from ghstats.web.github_oauth import (
    GitHubOAuthError,
    build_authorize_url,
    exchange_code_for_token,
    fetch_github_user,
    generate_state,
)
from ghstats.web.jobs import process_next_job
from ghstats.web.models import Report, User
from ghstats.web.schemas import ReportCreatePayload
from ghstats.web.service import HostedReportService, serialize_report


TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def create_app(settings: WebAppSettings | None = None) -> FastAPI:
    web_settings = settings or load_web_settings()
    web_settings.report_storage_dir.mkdir(parents=True, exist_ok=True)
    engine, session_factory = create_engine_and_session_factory(web_settings.database_url)
    Base.metadata.create_all(bind=engine)

    app = FastAPI(title=web_settings.app_name)
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

    @app.get("/", response_class=HTMLResponse, response_model=None)
    def home(request: Request, user: User | None = Depends(optional_user)) -> HTMLResponse | RedirectResponse:
        if _is_report_host(request, web_settings):
            return _render_subdomain_report(request, web_settings, session_factory, user, report_path="")
        if user is not None:
            return RedirectResponse(url="/dashboard", status_code=302)
        return templates.TemplateResponse(
            request,
            "web/index.html.j2",
            {
                "settings": web_settings,
            },
        )

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
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            reports = [serialize_report(report, web_settings) for report in service.list_reports_for_user(db_user)]
        return templates.TemplateResponse(
            request,
            "web/dashboard.html.j2",
            {
                "settings": web_settings,
                "user": db_user,
                "reports": reports,
                "allow_sample_reports": web_settings.allow_sample_reports,
            },
        )

    @app.post("/dashboard/reports")
    def dashboard_create_report(
        request: Request,
        since_spec: str = Form("30d"),
        title: str = Form(""),
        include_private: str | None = Form(None),
        visibility: str = Form("unlisted"),
        expires_in_days: int = Form(14),
        store_metadata: str | None = Form(None),
        sample_data: str | None = Form(None),
        user: User = Depends(require_user),
    ) -> RedirectResponse:
        payload = ReportCreatePayload(
            since_spec=since_spec,
            title=title or None,
            include_private=include_private == "true",
            visibility=visibility,
            sample_data=sample_data == "true",
            store_metadata=store_metadata == "true",
            expires_in_days=expires_in_days,
        )
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            report = service.queue_report(
                user=db_user,
                since_spec=payload.since_spec,
                title=payload.title,
                include_private=payload.include_private,
                visibility=payload.visibility,
                store_metadata=payload.store_metadata,
                expires_in_days=payload.expires_in_days,
                sample_data=payload.sample_data,
            )
            if web_settings.process_jobs_inline:
                process_next_job(web_settings, session)
        return RedirectResponse(url=f"/dashboard/reports/{report.id}", status_code=302)

    @app.get("/dashboard/reports/{report_id}", response_class=HTMLResponse)
    def dashboard_report_detail(request: Request, report_id: str, user: User = Depends(require_user)) -> HTMLResponse:
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            report = service.get_report_for_user(db_user, report_id)
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found")
            snapshot = report.latest_snapshot
            report_data = serialize_report(report, web_settings)
        return templates.TemplateResponse(
            request,
            "web/report_detail.html.j2",
            {
                "settings": web_settings,
                "report": report_data,
                "snapshot": snapshot,
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
            report = service.queue_report(
                user=db_user,
                since_spec=payload.since_spec,
                title=payload.title,
                include_private=payload.include_private,
                visibility=payload.visibility,
                store_metadata=payload.store_metadata,
                expires_in_days=payload.expires_in_days,
                sample_data=payload.sample_data,
            )
            if web_settings.process_jobs_inline:
                process_next_job(web_settings, session)
            return serialize_report(report, web_settings)

    @app.get("/api/reports/{report_id}")
    def api_report_detail(report_id: str, user: User = Depends(require_user)) -> dict[str, object]:
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            report = service.get_report_for_user(db_user, report_id)
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found")
            payload = serialize_report(report, web_settings)
            payload["latest_snapshot_id"] = report.latest_snapshot_id
            payload["error_message"] = report.error_message
            return payload

    @app.post("/dashboard/reports/{report_id}/refresh")
    def dashboard_refresh_report(
        report_id: str,
        user: User = Depends(require_user),
    ) -> RedirectResponse:
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            report = service.get_report_for_user(db_user, report_id)
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found")
            service.queue_refresh(report=report, sample_data=False)
            if web_settings.process_jobs_inline:
                process_next_job(web_settings, session)
        return RedirectResponse(url=f"/dashboard/reports/{report_id}", status_code=302)

    @app.post("/api/reports/{report_id}/refresh")
    def api_refresh_report(
        report_id: str,
        payload: ReportCreatePayload | None = None,
        user: User = Depends(require_user),
    ) -> dict[str, object]:
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            service = HostedReportService(web_settings, session)
            report = service.get_report_for_user(db_user, report_id)
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found")
            report = service.queue_refresh(
                report=report,
                sample_data=payload.sample_data if payload else False,
            )
            if web_settings.process_jobs_inline:
                process_next_job(web_settings, session)
            return serialize_report(report, web_settings)

    @app.get("/api/jobs/{job_id}")
    def api_job_detail(job_id: str, user: User = Depends(require_user)) -> dict[str, object]:
        with session_factory() as session:
            db_user = session.get(User, user.id)
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")
            report = (
                session.query(Report)
                .filter(Report.user_id == db_user.id, Report.latest_job_id == job_id)
                .one_or_none()
            )
            if report is None or report.latest_job is None:
                raise HTTPException(status_code=404, detail="Job not found")
            job = report.latest_job
            return {
                "id": job.id,
                "report_id": report.id,
                "status": job.status,
                "job_type": job.job_type,
                "error_message": job.error_message,
                "created_at": job.created_at.isoformat(),
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            }

    @app.get("/r/{slug}")
    def public_report(slug: str, request: Request, user: User | None = Depends(optional_user)) -> HTMLResponse:
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


def _none_or_str(value: object | None) -> str | None:
    if value is None:
        return None
    return str(value)


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
        html = service.read_snapshot_html(report.latest_snapshot)
    return HTMLResponse(content=html)


app = create_app()


def run() -> None:
    settings = load_web_settings()
    uvicorn.run(
        "ghstats.web.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
    )
