from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

try:
    import jwt  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - handled by runtime checks
    jwt = None


class GitHubAppError(RuntimeError):
    """Raised when the GitHub App publish flow is misconfigured or fails."""


@dataclass(slots=True)
class GitHubAppSettings:
    app_id: str
    private_key: str
    app_slug: str
    api_url: str = "https://api.github.com"
    app_url: str = "https://github.com/apps"


class GitHubProfilePublisher:
    def __init__(self, settings: GitHubAppSettings) -> None:
        self.settings = settings

    def build_install_url(self, owner: str, repo: str) -> str:
        slug = self.settings.app_slug.strip()
        if not slug:
            raise GitHubAppError("GitHub App slug is not configured.")
        return f"{self.settings.app_url.rstrip('/')}/{slug}/installations/new"

    def fetch_current_readme(self, *, installation_id: int, owner: str, repo: str) -> dict[str, Any]:
        token = self._create_installation_token(installation_id)
        with self._client(token) as client:
            response = client.get(f"/repos/{owner}/{repo}/contents/README.md")
        if response.status_code == 404:
            return {"exists": False, "content": "", "sha": None}
        response.raise_for_status()
        payload = response.json()
        import base64

        content = base64.b64decode(payload.get("content", "").encode("ascii")).decode("utf-8")
        return {"exists": True, "content": content, "sha": payload.get("sha")}

    def publish_readme(
        self,
        *,
        installation_id: int,
        owner: str,
        repo: str,
        markdown_body: str,
        sha: str | None,
        commit_message: str,
    ) -> str:
        token = self._create_installation_token(installation_id)
        import base64

        payload: dict[str, Any] = {
            "message": commit_message,
            "content": base64.b64encode(markdown_body.encode("utf-8")).decode("ascii"),
        }
        if sha:
            payload["sha"] = sha
        with self._client(token) as client:
            response = client.put(f"/repos/{owner}/{repo}/contents/README.md", json=payload)
        response.raise_for_status()
        result = response.json()
        commit = result.get("commit") or {}
        return str(commit.get("sha") or "")

    def verify_profile_repo_installation(self, *, installation_id: int, owner: str, repo: str) -> None:
        bearer = self._create_app_jwt()
        installation_response = httpx.get(
            f"{self.settings.api_url.rstrip('/')}/app/installations/{installation_id}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {bearer}",
                "User-Agent": "ghstatsussy-hosted",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
        installation_response.raise_for_status()
        installation = installation_response.json()
        account = installation.get("account") or {}
        if str(account.get("login") or "").lower() != owner.lower():
            raise GitHubAppError("GitHub App installation is not attached to the expected profile owner.")
        if str(installation.get("repository_selection") or "") != "selected":
            raise GitHubAppError("GitHub App installation must be limited to selected repositories, not all repositories.")

        token = self._create_installation_token(installation_id)
        with self._client(token) as client:
            repos_response = client.get("/installation/repositories?per_page=100")
        repos_response.raise_for_status()
        repos_payload = repos_response.json()
        repositories = repos_payload.get("repositories") or []
        expected_full_name = f"{owner}/{repo}".lower()
        names = [str(item.get("full_name") or "").lower() for item in repositories]
        if expected_full_name not in names:
            raise GitHubAppError("GitHub App installation cannot access the configured profile repository.")
        if len(names) != 1:
            raise GitHubAppError("GitHub App installation must be scoped to the single profile repository only.")

    def _create_installation_token(self, installation_id: int) -> str:
        bearer = self._create_app_jwt()
        response = httpx.post(
            f"{self.settings.api_url.rstrip('/')}/app/installations/{installation_id}/access_tokens",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {bearer}",
                "User-Agent": "ghstatsussy-hosted",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("token")
        if not token:
            raise GitHubAppError("GitHub App installation token was not returned.")
        return str(token)

    def _create_app_jwt(self) -> str:
        if jwt is None:
            raise GitHubAppError("PyJWT is not installed. Add it to dependencies before using GitHub App publishing.")
        if not self.settings.app_id or not self.settings.private_key:
            raise GitHubAppError("GitHub App credentials are not configured.")
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 540, "iss": self.settings.app_id}
        token = jwt.encode(payload, self.settings.private_key, algorithm="RS256")
        return str(token)

    def _client(self, token: str) -> httpx.Client:
        return httpx.Client(
            base_url=self.settings.api_url.rstrip("/"),
            timeout=30.0,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "ghstatsussy-hosted",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
