"""Helpers behind the MCP host's OAuth routes (/authorize, /token, /register in server.py).

The hosted server serves its own authorization-server metadata and forwards the OAuth
protocol messages to the dashboard, the real authorization server, which runs consent
and mints and validates every token. Two things some clients get wrong would each
leave the user holding a token this server cannot use, so the proxy fills them in.
"""

import logging
from collections.abc import Mapping

import httpx
from starlette.responses import Response

from .api_client import _sanitize

logger = logging.getLogger(__name__)


def map_openid_scope(params: dict, endpoint: str) -> dict:
    """``params`` with scope ``all`` when the requested scope includes ``openid``.

    Some clients request ``openid`` by default. This server implements no OpenID
    Connect, and the dashboard drops scopes it doesn't know, so such a client would
    get a token with no scope, which every API call refuses. Registration needs it
    too: the dashboard caps a client's scopes at the ones it registered with. Only
    ``openid`` is special: scopes that are all unsupported are returned unchanged.
    """
    scope = params.get("scope")
    if isinstance(scope, str) and "openid" in scope.split():
        logger.info("oauth-proxy %s: mapped scope openid to all", endpoint)
        return {**params, "scope": "all"}
    return params


def authorize_params(params: Mapping[str, str], resource: str) -> dict:
    """The authorize parameters to forward: ``openid`` mapped, a missing ``resource`` defaulted.

    The MCP authorization spec requires clients to send ``resource`` (RFC 8707). The
    dashboard binds the token to it, and introspection reports only tokens bound to
    this server as active, so without it every request made with the new token gets
    a 401. A client reaches this endpoint through this server's own metadata, so this
    server is the resource it wants; RFC 8707 section 2.1 lets an authorization server
    apply such a default. A blank ``resource`` counts as missing.
    """
    params = map_openid_scope(dict(params), "/authorize")
    if params.get("resource"):
        return params
    logger.info(
        "oauth-proxy /authorize: defaulted resource for client_id=%s", params.get("client_id", "?")
    )
    return {**params, "resource": resource}


async def proxy_post(
    dashboard: str, path: str, *, json: dict | None = None, data: dict | None = None
) -> Response:
    """POST a JSON or form body to ``dashboard + path`` and return the dashboard's answer unchanged."""
    async with httpx.AsyncClient(timeout=30.0) as http:
        r = await http.post(f"{dashboard}{path}", json=json, data=data)
    if 400 <= r.status_code < 500:
        # Claude's own grants come through here, and a rejection is returned to it
        # verbatim with no record of why — the dashboard signals invalid_grant vs
        # invalid_scope vs invalid_request only in the body, all as 400. Log the
        # grant type and that body so a failed refresh is diagnosable.
        # 4xx only: a 5xx on a DEBUG=True env renders a traceback whose locals hold
        # credentials. The REQUEST body is never logged — it carries the refresh
        # token, the auth code and the PKCE verifier.
        logger.warning(
            "oauth-proxy %s grant=%s -> %s: %s",
            path,
            (data or {}).get("grant_type", "?"),
            r.status_code,
            _sanitize(r.text[:300]),
        )
    return Response(
        content=r.content,
        status_code=r.status_code,
        media_type=r.headers.get("content-type", "application/json"),
    )
