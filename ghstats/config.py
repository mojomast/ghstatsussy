from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from ghstats import __version__


class ConfigError(RuntimeError):
    """Raised when runtime configuration is invalid."""


class TokenProvider(Protocol):
    def get_token(self) -> str | None:
        """Return an access token if available."""


@dataclass(slots=True)
class EnvironmentTokenProvider:
    env_keys: tuple[str, ...] = ("GITHUB_TOKEN", "GH_TOKEN")

    def get_token(self) -> str | None:
        for key in self.env_keys:
            value = os.getenv(key, "").strip()
            if value:
                return value
        gh_token = os.getenv("GH_ACCESS_TOKEN", "").strip()
        if gh_token:
            return gh_token
        return None


@dataclass(slots=True)
class StaticTokenProvider:
    token: str | None

    def get_token(self) -> str | None:
        return (self.token or "").strip() or None


@dataclass(slots=True)
class RuntimeConfig:
    token_provider: TokenProvider
    api_base_url: str = "https://api.github.com"
    graphql_url: str = "https://api.github.com/graphql"
    timeout_seconds: float = 30.0
    user_agent: str = f"ghstats/{__version__}"
    include_private: bool = False
    repo_page_size: int = 100
    max_repos_for_commit_scan: int = 40
    max_commit_pages_per_repo: int = 5
    max_commit_details: int = 200
    search_page_size: int = 50
    max_search_items: int = 200
    retry_attempts: int = 3


def resolve_graphql_url(api_base_url: str) -> str:
    normalized = api_base_url.rstrip("/")
    if normalized == "https://api.github.com":
        return f"{normalized}/graphql"
    if normalized.endswith("/api/v3"):
        return f"{normalized[:-7]}/api/graphql"
    return f"{normalized}/graphql"


def build_runtime_config(
    *,
    token: str | None = None,
    include_private: bool = False,
    api_base_url: str = "https://api.github.com",
) -> RuntimeConfig:
    token_provider: TokenProvider
    if token is not None:
        token_provider = StaticTokenProvider(token=token)
    else:
        token_provider = EnvironmentTokenProvider()

    return RuntimeConfig(
        token_provider=token_provider,
        api_base_url=api_base_url.rstrip("/"),
        graphql_url=resolve_graphql_url(api_base_url),
        include_private=include_private,
    )
