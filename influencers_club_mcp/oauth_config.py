"""Single source of truth for OAuth resource-server configuration.

Both the token verifier (``auth.build_auth``) and the upstream API client
(``api_client.InfluencersApiClient``) read the dashboard URLs and confidential
client credentials from here, so introspection, token-exchange, API calls and the
advertised issuer can never drift out of sync.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# The IC dashboard doubles as the OAuth authorization server and the API host.
DEFAULT_DASHBOARD = "https://api-dashboard.influencers.club"
# Fallback MCP resource identifier when OAUTH_RESOURCE_URL is unset (local dev).
DEFAULT_RESOURCE = "http://localhost:8000/mcp"


def _first_env(*names: str) -> str:
    """First non-empty, stripped env value among ``names`` ('' counts as unset)."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class OAuthConfig:
    """Resolved OAuth settings. ``enabled`` gates HTTP-mode resource-server auth."""

    enabled: bool
    issuer: str
    api_base: str
    resource: str
    client_id: str
    client_secret: str
    scopes: list[str]
    cache_ttl: float


def load_oauth_config() -> OAuthConfig:
    """Resolve OAuth configuration from the environment with consistent fallbacks.

    ``issuer`` and ``api_base`` share one precedence rule — each prefers its own
    variable, then cross-falls-back to the other, then the prod default — so the
    advertised authorization server and the host actually called always agree.
    Empty-string values are treated as unset.
    """
    issuer = (
        _first_env("OAUTH_ISSUER_URL", "OAUTH_API_BASE") or DEFAULT_DASHBOARD
    ).rstrip("/")
    api_base = (
        _first_env("OAUTH_API_BASE", "OAUTH_ISSUER_URL") or DEFAULT_DASHBOARD
    ).rstrip("/")
    try:
        cache_ttl = float(os.environ.get("OAUTH_CACHE_TTL", "60"))
    except ValueError:
        cache_ttl = 60.0
    return OAuthConfig(
        enabled=_truthy("MCP_OAUTH_ENABLED"),
        issuer=issuer,
        api_base=api_base,
        # Must match the dashboard + client byte-for-byte, so never slash-normalized.
        resource=_first_env("OAUTH_RESOURCE_URL") or DEFAULT_RESOURCE,
        client_id=_first_env("MCP_OAUTH_CLIENT_ID"),
        client_secret=_first_env("MCP_OAUTH_CLIENT_SECRET"),
        scopes=[
            s.strip()
            for s in os.environ.get("OAUTH_SCOPES", "").split(",")
            if s.strip()
        ],
        cache_ttl=cache_ttl,
    )
