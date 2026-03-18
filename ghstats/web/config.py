from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class WebAppSettings:
    app_name: str
    app_base_url: str
    secret_key: str
    database_url: str
    report_storage_dir: Path
    github_client_id: str
    github_client_secret: str
    github_oauth_scopes: tuple[str, ...]
    github_authorize_url: str
    github_token_url: str
    github_user_api_url: str
    github_user_email_api_url: str
    session_cookie_name: str
    allow_sample_reports: bool
    default_visibility: str
    default_report_expiry_days: int
    default_store_metadata: bool
    ghstats_subdomain_base: str
    reserved_report_usernames: tuple[str, ...]
    process_jobs_inline: bool
    host: str
    port: int
    reload: bool

    @property
    def github_callback_url(self) -> str:
        return f"{self.app_base_url}/auth/github/callback"


def load_web_settings() -> WebAppSettings:
    root_dir = Path(__file__).resolve().parents[2]
    default_db = root_dir / "web_artifacts" / "ghstatsussy.db"
    default_storage = root_dir / "web_artifacts"
    scopes = tuple(
        scope.strip()
        for scope in os.getenv("GITHUB_OAUTH_SCOPES", "read:user,user:email").split(",")
        if scope.strip()
    )

    default_visibility = os.getenv("DEFAULT_REPORT_VISIBILITY", "unlisted").strip().lower()
    if default_visibility not in {"private", "unlisted", "public"}:
        default_visibility = "unlisted"

    expiry_days = int(os.getenv("DEFAULT_REPORT_EXPIRY_DAYS", "14"))
    expiry_days = max(1, min(expiry_days, 90))

    return WebAppSettings(
        app_name=os.getenv("APP_NAME", "ghstatsussy hosted"),
        app_base_url=os.getenv("APP_BASE_URL", "http://127.0.0.1:8001").rstrip("/"),
        secret_key=os.getenv("APP_SECRET_KEY", "dev-secret-change-me"),
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{default_db}"),
        report_storage_dir=Path(os.getenv("REPORT_STORAGE_DIR", str(default_storage))).resolve(),
        github_client_id=os.getenv("GITHUB_CLIENT_ID", "").strip(),
        github_client_secret=os.getenv("GITHUB_CLIENT_SECRET", "").strip(),
        github_oauth_scopes=scopes,
        github_authorize_url=os.getenv(
            "GITHUB_AUTHORIZE_URL",
            "https://github.com/login/oauth/authorize",
        ),
        github_token_url=os.getenv(
            "GITHUB_TOKEN_URL",
            "https://github.com/login/oauth/access_token",
        ),
        github_user_api_url=os.getenv(
            "GITHUB_USER_API_URL",
            "https://api.github.com/user",
        ),
        github_user_email_api_url=os.getenv(
            "GITHUB_USER_EMAIL_API_URL",
            "https://api.github.com/user/emails",
        ),
        session_cookie_name=os.getenv("SESSION_COOKIE_NAME", "ghstatsussy_session"),
        allow_sample_reports=_truthy(os.getenv("ALLOW_SAMPLE_REPORTS", "0")),
        default_visibility=default_visibility,
        default_report_expiry_days=expiry_days,
        default_store_metadata=_truthy(os.getenv("DEFAULT_STORE_METADATA", "0")),
        ghstats_subdomain_base=os.getenv("GHSTATS_SUBDOMAIN_BASE", "ghstats.ussyco.de"),
        reserved_report_usernames=tuple(
            value.strip()
            for value in os.getenv(
                "RESERVED_REPORT_USERNAMES",
                "www,api,admin,assets,static,auth,dashboard",
            ).split(",")
            if value.strip()
        ),
        process_jobs_inline=_truthy(os.getenv("PROCESS_JOBS_INLINE", "1")),
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8001")),
        reload=_truthy(os.getenv("APP_RELOAD", "0")),
    )
