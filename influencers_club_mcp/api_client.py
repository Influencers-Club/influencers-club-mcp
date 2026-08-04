"""
HTTP client for the Influencers.club API.
Handles authentication, rate limiting, timeouts, error normalization,
credential redaction, and debug logging to stderr.
"""

import json
import os
import re
import sys
import time
from typing import Any

import httpx

from .auth import invalidate_cached_token
from .oauth_config import load_oauth_config

try:
    # Available when running under FastMCP HTTP transport with auth wired up.
    # In stdio mode this import succeeds but get_access_token() returns None.
    from mcp.server.auth.middleware.auth_context import get_access_token
except Exception:  # pragma: no cover — defensive against package layout drift
    def get_access_token():  # type: ignore[misc]
        return None

DEFAULT_TIMEOUT = 30.0
BATCH_TIMEOUT = 60.0
RATE_LIMIT = 300  # requests per minute
RATE_WINDOW = 60.0  # seconds

_BEARER_RE = re.compile(r"Bearer\s+\S+")


def _sanitize(text: str) -> str:
    """Redact Bearer tokens from error messages."""
    return _BEARER_RE.sub("Bearer [REDACTED]", text)


def _log(msg: str) -> None:
    """Log to stderr (stdio servers must not write to stdout)."""
    print(f"[MCP] {msg}", file=sys.stderr)


class RateLimitError(Exception):
    """Raised when client-side rate limit is exceeded."""
    pass


class ApiError(Exception):
    """Structured API error with status code and retryability."""

    def __init__(self, status: int, message: str, retryable: bool = False):
        self.status = status
        self.message = _sanitize(message)
        self.retryable = retryable
        super().__init__(self.message)


class _SlidingWindowRateLimiter:
    """Sliding window rate limiter to stay under API limits."""

    def __init__(self, max_per_window: int, window_seconds: float):
        self._max = max_per_window
        self._window = window_seconds
        self._timestamps: list[float] = []

    def check(self) -> None:
        now = time.time()
        cutoff = now - self._window
        self._timestamps = [t for t in self._timestamps if t > cutoff]
        if len(self._timestamps) >= self._max:
            raise RateLimitError(
                f"Client-side rate limit reached ({self._max} requests per {self._window}s). "
                "Please wait before making more requests."
            )
        self._timestamps.append(now)


class InfluencersApiClient:
    """Async HTTP client for the Influencers.club API.

    Token resolution is per-request to support both modes:
      - stdio (single-tenant): token comes from INFLUENCERS_CLUB_API_KEY env var
      - HTTP (multi-tenant, post-OAuth): token comes from the authenticated
        request via FastMCP's auth context (get_access_token).
    """

    def __init__(self) -> None:
        env_key = os.environ.get("INFLUENCERS_CLUB_API_KEY", "").strip()
        if env_key.startswith("Bearer "):
            env_key = env_key[7:].strip()
        self._env_api_key = env_key  # may be empty in HTTP mode

        # OAuth (HTTP) mode: the dashboard base + confidential client come from the
        # shared resolver, so introspection (auth), token-exchange and API calls
        # always target the same host with the same credentials.
        _oauth = load_oauth_config()
        self._base_url = _oauth.api_base
        self._oauth_client_id = _oauth.client_id
        self._oauth_client_secret = _oauth.client_secret
        # Per-subject-token cache of exchanged dashboard tokens:
        # {user_token: (dashboard_token, monotonic_expiry)}.
        self._exchange_cache: dict[str, tuple[str, float]] = {}

        max_rate = int(os.environ.get("MAX_CALLS_PER_MINUTE", str(RATE_LIMIT)))
        self._rate_limiter = _SlidingWindowRateLimiter(max_rate, RATE_WINDOW)
        self._client: httpx.AsyncClient | None = None

    async def _resolve_token(self) -> str:
        """Resolve the bearer token to send to the dashboard API.

        OAuth (HTTP) mode: the per-request access token is the user's MCP-audience
        token; per RFC 8693 we MUST NOT forward it to the API. Instead we exchange
        it (as a confidential client) for a separate dashboard-audience token and
        send that. stdio mode: fall back to the single env API key.
        """
        access_token = get_access_token()
        if access_token and access_token.token:
            tok = access_token.token
            user_token = tok[7:].strip() if tok.startswith("Bearer ") else tok
            return await self._exchange_token(user_token)
        if self._env_api_key:
            return self._env_api_key
        raise ApiError(
            401,
            "No bearer token available — provide INFLUENCERS_CLUB_API_KEY (stdio) "
            "or authenticate via OAuth (HTTP).",
        )

    async def _exchange_token(self, user_token: str) -> str:
        """Exchange the user's MCP-audience token for a dashboard-audience token
        (RFC 8693 token exchange), authenticating as the MCP confidential client.
        Cached per user token until shortly before the exchanged token expires."""
        now = time.monotonic()
        hit = self._exchange_cache.get(user_token)
        if hit and hit[1] > now:
            return hit[0]
        if not self._oauth_client_id or not self._oauth_client_secret:
            raise ApiError(
                500,
                "OAuth client credentials not configured (MCP_OAUTH_CLIENT_ID / "
                "MCP_OAUTH_CLIENT_SECRET) — cannot exchange the user token.",
            )
        client = await self._get_client()
        try:
            resp = await client.post(
                "/public/v1/oauth/token/",
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                    "client_id": self._oauth_client_id,
                    "client_secret": self._oauth_client_secret,
                    "subject_token": user_token,
                    "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                },
                timeout=DEFAULT_TIMEOUT,
            )
            if 400 <= resp.status_code < 500:
                # The dashboard returns an OAuth error code in the body
                # (invalid_grant vs invalid_scope vs invalid_request), all as 400.
                # raise_for_status() drops it, leaving the failures
                # indistinguishable in the logs — surface it before raising.
                # 4xx only: these bodies are fixed OAuth error strings, whereas a
                # 5xx on a DEBUG=True env renders a traceback whose locals hold the
                # subject token and client secret.
                _log(
                    f"token-exchange {resp.status_code}: "
                    f"{_sanitize(resp.text[:300])}"
                )
                if "invalid_grant" in resp.text:
                    # The dashboard will not exchange this subject token, which means
                    # it is no longer active there — almost always because the user
                    # refreshed and the previous access token was deactivated, while
                    # our admission cache still vouches for it. Drop the cache entry
                    # so the next request re-introspects and gets the authoritative
                    # answer, and report 401 rather than the upstream 400: 400 reads
                    # as a permanent tool failure and strands the session until the
                    # user re-authorizes by hand, whereas 401 is the signal to renew.
                    self._exchange_cache.pop(user_token, None)
                    evicted = invalidate_cached_token(user_token)
                    _log(
                        "token-exchange rejected the subject token; cleared "
                        f"admission cache (hit={evicted}) and signalling re-auth"
                    )
                    raise ApiError(
                        401,
                        "Access token is no longer valid upstream; re-authenticate.",
                    )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            raise self._handle_error(e) from e
        dash_token = payload.get("access_token")
        if not dash_token:
            raise ApiError(502, "Token exchange returned no access_token.")
        # Re-exchange ~30s before expiry so we never send a just-expired token.
        ttl = max(int(payload.get("expires_in") or 0) - 30, 0)
        self._exchange_cache[user_token] = (dash_token, now + ttl)
        return dash_token

    async def _get_client(self) -> httpx.AsyncClient:
        """Return a shared AsyncClient, creating it lazily on first use."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Accept": "application/json"},
                timeout=DEFAULT_TIMEOUT,
            )
        return self._client

    async def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {await self._resolve_token()}",
            "Accept": "application/json",
        }

    def _handle_error(self, e: Exception) -> ApiError:
        """Normalize exceptions into ApiError with credential redaction."""
        if isinstance(e, ApiError):
            return e
        if isinstance(e, httpx.HTTPStatusError):
            status = e.response.status_code
            try:
                body = e.response.json()
                msg = None
                if isinstance(body, dict):
                    msg = (body.get("message") or body.get("detail") or body.get("error")
                           or body.get("response_meta", {}).get("error_message"))
                if not msg:
                    # No recognized message key (e.g. DRF field-error dicts like
                    # {"filters": {"engagement_percent": [...]}} or list bodies) —
                    # include the body itself so the caller sees what was rejected.
                    msg = f"API error {status}: {_sanitize(json.dumps(body, ensure_ascii=False)[:300])}"
            except Exception:
                msg = f"API error {status}: {_sanitize(e.response.text[:200])}"
            return ApiError(status, str(msg), retryable=(status == 429 or status >= 500))
        if isinstance(e, httpx.TimeoutException):
            return ApiError(408, "Request timed out", retryable=True)
        if isinstance(e, RateLimitError):
            return ApiError(429, str(e), retryable=True)
        return ApiError(0, _sanitize(str(e)), retryable=False)

    async def get(
        self, path: str, params: dict[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT
    ) -> Any:
        """Make a GET request."""
        _log(f"GET {path} params={params}")
        client = await self._get_client()
        try:
            # Inside the try so RateLimitError normalizes to ApiError(429, retryable=True)
            self._rate_limiter.check()
            resp = await client.get(
                path,
                params=params,
                headers=await self._headers(),
                timeout=timeout,
            )
            _log(f"GET {path} -> {resp.status_code}")
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                return resp.json()
            return resp.text
        except Exception as e:
            raise self._handle_error(e) from e

    async def post(self, path: str, body: dict[str, Any], timeout: float = DEFAULT_TIMEOUT) -> Any:
        """Make a POST request with JSON body."""
        _log(f"POST {path}")
        client = await self._get_client()
        try:
            self._rate_limiter.check()
            resp = await client.post(
                path,
                json=body,
                headers={**(await self._headers()), "Content-Type": "application/json"},
                timeout=timeout,
            )
            _log(f"POST {path} -> {resp.status_code}")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            raise self._handle_error(e) from e

    async def post_multipart(
        self, path: str, files: dict, data: dict[str, str], timeout: float = BATCH_TIMEOUT
    ) -> Any:
        """Make a POST request with multipart/form-data (for batch uploads)."""
        _log(f"POST {path} (multipart) mode={data.get('enrichment_mode', '?')}")
        client = await self._get_client()
        try:
            self._rate_limiter.check()
            resp = await client.post(
                path,
                files=files,
                data=data,
                headers=await self._headers(),
                timeout=timeout,
            )
            _log(f"POST {path} -> {resp.status_code}")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            raise self._handle_error(e) from e
