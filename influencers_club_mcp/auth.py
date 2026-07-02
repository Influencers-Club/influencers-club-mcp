"""OAuth 2.1 resource-server token validation for hosted (HTTP) mode.

The Influencers Club dashboard (``api-dashboard.influencers.club``) is the OAuth
authorization server. It issues **opaque** access tokens, so this MCP server (a
separate resource server) cannot validate them locally. Per the MCP authorization
spec it MUST validate that a presented token was issued *for it* and MUST NOT pass
the token through to the upstream API.

This verifier therefore validates a bearer token via the dashboard's RFC 7662
**token-introspection** endpoint (``POST /public/v1/oauth/introspect/``),
authenticating as a confidential client (``client_secret_post``). It accepts the
token only if the introspection response is ``active`` **and** its ``aud`` equals
this MCP's own resource URL. The token is never forwarded to the API as a
credential — the upstream call uses a separately exchanged token (see
``api_client``).

Successful validations are cached for a short TTL so we don't introspect on every
single MCP request (``verify_token`` runs per request).

Wiring lives in ``server.py`` and is only active in HTTP mode when
``MCP_OAUTH_ENABLED`` is truthy, so stdio and the current no-auth HTTP deploy
are unaffected.
"""

from __future__ import annotations

import sys
import time

import httpx
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings

from .oauth_config import load_oauth_config

# RFC 7662 token-introspection endpoint on the dashboard.
_INTROSPECT_PATH = "/public/v1/oauth/introspect/"


def _log(msg: str) -> None:
    print(f"[MCP auth] {msg}", file=sys.stderr)


class ICTokenVerifier(TokenVerifier):
    """Validate dashboard-issued OAuth tokens via RFC 7662 introspection.

    Opaque tokens can't be verified locally, so we ask the dashboard's
    introspection endpoint (authenticating as a confidential client) and accept
    only tokens that are active AND audience-bound to this MCP server.
    """

    def __init__(
        self,
        api_base: str,
        client_id: str,
        client_secret: str,
        resource_url: str,
        scopes: list[str],
        cache_ttl: float = 60.0,
    ) -> None:
        self._introspect_url = api_base.rstrip("/") + _INTROSPECT_PATH
        self._client_id = client_id
        self._client_secret = client_secret
        self._resource = resource_url
        self._scopes = scopes
        self._cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, AccessToken]] = {}

    async def verify_token(self, token: str) -> AccessToken | None:
        now = time.monotonic()
        hit = self._cache.get(token)
        if hit and hit[0] > now:
            return hit[1]

        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.post(
                    self._introspect_url,
                    data={
                        "token": token,
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                    headers={"Accept": "application/json"},
                )
        except Exception as exc:  # network/timeout → fail closed, don't cache
            _log(f"introspection FAILED (network): {type(exc).__name__}: {exc}")
            return None

        if resp.status_code != 200:
            # 401 here means OUR client credentials are wrong (misconfig), not the
            # user's token. Either way, fail closed.
            _log(f"introspection returned {resp.status_code}; rejecting")
            self._cache.pop(token, None)
            return None

        try:
            data = resp.json()
        except Exception:
            _log("introspection response was not JSON; rejecting")
            return None

        if not data.get("active"):
            self._cache.pop(token, None)
            return None

        # MUST validate the token was issued for THIS resource server (RFC 8707 /
        # MCP spec). The dashboard reports the bound resource as `aud`, which per
        # RFC 7662 may be a single string OR a list of strings.
        aud = data.get("aud")
        audiences = [aud] if isinstance(aud, str) else (aud or [])
        if self._resource not in audiences:
            _log(
                f"token audience {aud!r} != our resource "
                f"{self._resource!r}; rejecting"
            )
            return None

        # Use exactly the scopes introspection granted — never fall back to the
        # configured scopes, or a no-scope token would look authorized for them.
        scope_str = data.get("scope") or ""
        scopes = scope_str.split()
        exp = data.get("exp")
        access = AccessToken(
            token=token,
            client_id=str(data.get("sub") or "influencers-club-mcp"),
            scopes=scopes,
            expires_at=int(exp) if exp else None,
            resource=self._resource,
        )
        # Trust the introspection result for a short window; never past the token's
        # own expiry.
        ttl = self._cache_ttl
        if exp:
            ttl = min(ttl, max(int(exp) - int(time.time()), 0))
        self._cache[token] = (now + ttl, access)
        return access


def build_auth() -> tuple[ICTokenVerifier | None, AuthSettings | None]:
    """Return ``(token_verifier, AuthSettings)`` for HTTP mode, or ``(None, None)``.

    OAuth is opt-in via ``MCP_OAUTH_ENABLED`` so existing stdio / no-auth HTTP
    deployments are unaffected. Config (all read from env):

    ==========================  =================================================
    ``OAUTH_ISSUER_URL``        authorization-server issuer (default prod dashboard)
    ``OAUTH_API_BASE``          dashboard base for introspection (default = issuer)
    ``OAUTH_RESOURCE_URL``      this MCP's public canonical URL (RFC 9728 resource)
    ``MCP_OAUTH_CLIENT_ID``     this MCP's confidential client_id (introspection auth)
    ``MCP_OAUTH_CLIENT_SECRET`` its client secret (client_secret_post)
    ``OAUTH_SCOPES``            comma-separated scopes to require/advertise (default none)
    ``OAUTH_CACHE_TTL``         seconds to trust a validated token (default 60)
    ==========================  =================================================

    If credentials are missing while enabled, the verifier still builds but every
    introspection call will be rejected by the dashboard (fail-closed), which makes
    the misconfiguration loud rather than silently disabling auth.
    """
    cfg = load_oauth_config()
    if not cfg.enabled:
        return None, None

    if not cfg.client_id or not cfg.client_secret:
        _log(
            "WARNING: MCP_OAUTH_ENABLED but MCP_OAUTH_CLIENT_ID/SECRET are not set — "
            "introspection will fail closed (all tokens rejected)."
        )

    verifier = ICTokenVerifier(
        cfg.api_base,
        cfg.client_id,
        cfg.client_secret,
        cfg.resource,
        cfg.scopes,
        cache_ttl=cfg.cache_ttl,
    )
    settings = AuthSettings(
        issuer_url=cfg.issuer,
        resource_server_url=cfg.resource,
        required_scopes=cfg.scopes or None,
    )
    _log(
        f"OAuth enabled — issuer={cfg.issuer} resource={cfg.resource} "
        f"required_scopes={cfg.scopes or '(none)'}"
    )
    return verifier, settings
