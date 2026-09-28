"""Helpers behind the MCP host's OAuth routes (/authorize, /token, /register in server.py).

The hosted server serves its own authorization-server metadata and forwards the OAuth
protocol messages to the dashboard, the real authorization server, which runs consent
and mints and validates every token. Two things some clients get wrong would each
leave the user holding a token this server cannot use, so the proxy fills them in and
forwards everything else as sent.
"""

import json
import logging
import re
from urllib.parse import parse_qsl, urlencode

import httpx
from starlette.requests import Request
from starlette.responses import Response

from .api_client import _sanitize

logger = logging.getLogger(__name__)


def map_openid_scope(scope: str) -> str:
    """``all`` when ``openid`` is among the requested scopes, otherwise ``scope`` as sent.

    Some clients request ``openid`` by default. This server implements no OpenID
    Connect, and the dashboard drops scopes it doesn't know, so such a client would
    get a token with no scope, which every API call refuses. Only ``openid`` is
    special: a request whose scopes are all unsupported is forwarded unchanged.
    """
    return "all" if "openid" in scope.split() else scope


def authorize_query(query: str, resource: str) -> str:
    """The authorize query to forward, unchanged unless it lacks ``resource`` or asks for ``openid``.

    The MCP authorization spec requires clients to send ``resource`` (RFC 8707). The
    dashboard binds the token to it, and introspection reports only tokens bound to
    this server as active, so without it every request made with the new token gets
    a 401. A client reaches this endpoint through this server's own metadata, so this
    server is the resource it wants; RFC 8707 section 2.1 lets an authorization server
    apply such a default. A blank ``resource`` counts as missing.
    """
    params = parse_qsl(query, keep_blank_values=True)
    has_resource = any(name == "resource" and value for name, value in params)
    maps_scope = any(
        name == "scope" and map_openid_scope(value) != value for name, value in params
    )
    if has_resource and not maps_scope:
        return query
    params = [
        (name, map_openid_scope(value) if name == "scope" else value)
        for name, value in params
        if name != "resource" or value
    ]
    if not has_resource:
        params.append(("resource", resource))
    return urlencode(params)


def register_body(body: bytes) -> bytes:
    """The client-registration request to forward, with ``openid`` mapped in its scope.

    The dashboard caps a client's scopes at the scope it registered with, so a client
    registered with ``openid`` could never be granted ``all``, whatever it later asks
    for at /authorize. Anything other than a JSON object with a string ``scope`` is
    forwarded as sent, for the dashboard to judge.
    """
    try:
        data = json.loads(body)
    except ValueError:
        return body
    if not isinstance(data, dict) or not isinstance(data.get("scope"), str):
        return body
    scope = map_openid_scope(data["scope"])
    if scope == data["scope"]:
        return body
    return json.dumps({**data, "scope": scope}).encode()


async def proxy_post(
    request: Request, dashboard: str, path: str, body: bytes | None = None
) -> Response:
    """POST ``body`` (default: the request's own body) to ``dashboard + path`` and return
    the dashboard's answer unchanged."""
    if body is None:
        body = await request.body()
    ct = request.headers.get("content-type", "application/x-www-form-urlencoded")
    async with httpx.AsyncClient(timeout=30.0) as http:
        r = await http.post(f"{dashboard}{path}", content=body, headers={"Content-Type": ct})
    if 400 <= r.status_code < 500:
        # Claude's own grants come through here, and a rejection is returned to it
        # verbatim with no record of why — the dashboard signals invalid_grant vs
        # invalid_scope vs invalid_request only in the body, all as 400. Log the
        # grant type and that body so a failed refresh is diagnosable.
        # 4xx only: a 5xx on a DEBUG=True env renders a traceback whose locals hold
        # credentials. The REQUEST body is never logged — it carries the refresh
        # token, the auth code and the PKCE verifier.
        grant = re.search(rb"grant_type=([A-Za-z0-9_.:%-]+)", body)
        logger.warning(
            "oauth-proxy %s grant=%s -> %s: %s",
            path,
            grant.group(1).decode() if grant else "?",
            r.status_code,
            _sanitize(r.text[:300]),
        )
    return Response(
        content=r.content,
        status_code=r.status_code,
        media_type=r.headers.get("content-type", "application/json"),
    )
