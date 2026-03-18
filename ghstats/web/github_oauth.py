from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx

from ghstats.web.config import WebAppSettings


class GitHubOAuthError(RuntimeError):
    """Raised when GitHub OAuth fails."""


def generate_state() -> str:
    return secrets.token_urlsafe(24)


def build_authorize_url(settings: WebAppSettings, state: str) -> str:
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.github_callback_url,
        "scope": " ".join(settings.github_oauth_scopes),
        "state": state,
        "allow_signup": "true",
    }
    return f"{settings.github_authorize_url}?{urlencode(params)}"


def exchange_code_for_token(settings: WebAppSettings, code: str) -> dict[str, str]:
    response = httpx.post(
        settings.github_token_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ghstatsussy-hosted",
        },
        data={
            "client_id": settings.github_client_id,
            "client_secret": settings.github_client_secret,
            "code": code,
            "redirect_uri": settings.github_callback_url,
        },
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise GitHubOAuthError(payload.get("error_description") or payload["error"])
    if not payload.get("access_token"):
        raise GitHubOAuthError("GitHub did not return an access token.")
    return payload


def fetch_github_user(settings: WebAppSettings, access_token: str) -> dict[str, object]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "ghstatsussy-hosted",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(timeout=30.0, headers=headers) as client:
        user_response = client.get(settings.github_user_api_url)
        user_response.raise_for_status()
        user = user_response.json()

        email = user.get("email")
        if not email:
            email_response = client.get(settings.github_user_email_api_url)
            if email_response.status_code < 400:
                emails = email_response.json()
                primary = next((item for item in emails if item.get("primary")), None)
                verified = next((item for item in emails if item.get("verified")), None)
                chosen = primary or verified or (emails[0] if emails else None)
                if chosen:
                    email = chosen.get("email")

    return {
        "github_user_id": user["id"],
        "login": user["login"],
        "name": user.get("name"),
        "avatar_url": user.get("avatar_url"),
        "profile_url": user.get("html_url"),
        "email": email,
    }
