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

try:
    # Available when running under FastMCP HTTP transport with auth wired up.
    # In stdio mode this import succeeds but get_access_token() returns None.
    from mcp.server.auth.middleware.auth_context import get_access_token
except Exception:  # pragma: no cover — defensive against package layout drift
    def get_access_token():  # type: ignore[misc]
        return None

BASE_URL = "https://api-dashboard.influencers.club"
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

        max_rate = int(os.environ.get("MAX_CALLS_PER_MINUTE", str(RATE_LIMIT)))
        self._rate_limiter = _SlidingWindowRateLimiter(max_rate, RATE_WINDOW)
        self._client: httpx.AsyncClient | None = None

    def _resolve_token(self) -> str:
        """Resolve the bearer token for the current request.

        Order: per-request OAuth access token → env var fallback.
        Raises if neither is available.
        """
        access_token = get_access_token()
        if access_token and access_token.token:
            tok = access_token.token
            return tok[7:].strip() if tok.startswith("Bearer ") else tok
        if self._env_api_key:
            return self._env_api_key
        raise ApiError(
            401,
            "No bearer token available — provide INFLUENCERS_CLUB_API_KEY (stdio) "
            "or authenticate via OAuth (HTTP).",
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Return a shared AsyncClient, creating it lazily on first use."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=BASE_URL,
                headers={"Accept": "application/json"},
                timeout=DEFAULT_TIMEOUT,
            )
        return self._client

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._resolve_token()}",
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
                msg = (body.get("message") or body.get("detail") or body.get("error")
                       or body.get("response_meta", {}).get("error_message")
                       or f"API error {status}")
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
        self._rate_limiter.check()
        _log(f"GET {path} params={params}")
        client = await self._get_client()
        try:
            resp = await client.get(
                path,
                params=params,
                headers=self._headers(),
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
        self._rate_limiter.check()
        _log(f"POST {path} body={json.dumps(body, default=str)[:500]}")
        client = await self._get_client()
        try:
            resp = await client.post(
                path,
                json=body,
                headers={**self._headers(), "Content-Type": "application/json"},
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
        self._rate_limiter.check()
        _log(f"POST {path} (multipart) mode={data.get('enrichment_mode', '?')}")
        client = await self._get_client()
        try:
            resp = await client.post(
                path,
                files=files,
                data=data,
                headers=self._headers(),
                timeout=timeout,
            )
            _log(f"POST {path} -> {resp.status_code}")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            raise self._handle_error(e) from e
