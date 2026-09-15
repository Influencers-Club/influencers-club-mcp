"""Tool calls exchange the token of the request that carried them.

In stateful streamable HTTP every message of a session is handled inside a task
started while the session's initialize request was being served, so the SDK's
get_access_token() keeps returning the token the session was opened with, even
after the client has rotated it. The server must hand the API client the token
the auth middleware verified for the current message's own HTTP request instead.
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel.server import request_ctx
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.context import RequestContext
from mcp.types import LATEST_PROTOCOL_VERSION
from starlette.authentication import BaseUser, UnauthenticatedUser
from starlette.requests import Request

from influencers_club_mcp.api_client import ApiError, InfluencersApiClient
from influencers_club_mcp.server import _request_token

RESOURCE = "https://mcp.test/mcp"


def access(token: str) -> AccessToken:
    """An admitted token. Its principal is the part before the dot: alice.2 -> alice."""
    return AccessToken(
        token=token,
        client_id=token.split(".")[0],
        scopes=[],
        expires_at=None,
        resource=RESOURCE,
    )


def authenticated(token: str) -> AuthenticatedUser:
    """The user the auth middleware stores for a request whose bearer it admitted."""
    return AuthenticatedUser(access(token))


def http_request(user: BaseUser | None = None) -> Request:
    """An HTTP request carrying the user the auth middleware stored, if it ran at all.

    Behind the middleware there is always a user: AuthenticatedUser, or
    UnauthenticatedUser when the bearer was missing or rejected.
    """
    scope = {"type": "http", "headers": []}
    if user is not None:
        scope["user"] = user
    return Request(scope)


def message_context(request: Request | None) -> RequestContext:
    """What the SDK sets while it handles one message (stdio messages have no request)."""
    return RequestContext(
        request_id=1, meta=None, session=None, lifespan_context=None, request=request
    )


@pytest.fixture
def exchanged(monkeypatch):
    """Subject tokens handed to token exchange, in order. The exchange is stubbed."""
    seen: list[str] = []

    async def exchange(self, user_token: str) -> str:
        seen.append(user_token)
        return f"dashboard-{user_token}"

    monkeypatch.setattr(InfluencersApiClient, "_exchange_token", exchange)
    return seen


def test_rotated_token_is_exchanged_not_the_one_the_session_opened_with(exchanged):
    async def scenario():
        # The session's task inherited the token of the initialize request...
        auth_context_var.set(authenticated("alice.1"))
        # ...while this message came in on a request carrying the rotated token.
        request_ctx.set(message_context(http_request(authenticated("alice.2"))))
        return await InfluencersApiClient(request_token=_request_token)._resolve_token()

    assert asyncio.run(scenario()) == "dashboard-alice.2"
    assert exchanged == ["alice.2"]


def test_concurrent_calls_each_exchange_their_own_request_token(exchanged):
    client = InfluencersApiClient(request_token=_request_token)

    async def call(token: str) -> str:
        request_ctx.set(message_context(http_request(authenticated(token))))
        await asyncio.sleep(0)  # let the other call set its context before we resolve
        return await client._resolve_token()

    async def scenario():
        return await asyncio.gather(call("alice.1"), call("bob.1"))

    assert asyncio.run(scenario()) == ["dashboard-alice.1", "dashboard-bob.1"]


@pytest.mark.parametrize(
    "context",
    [
        None,
        message_context(None),
        message_context(http_request(UnauthenticatedUser())),
        message_context(http_request()),
    ],
    ids=[
        "outside-any-message",
        "message-without-http-request",
        "unauthenticated-request",
        "request-the-auth-middleware-never-saw",
    ],
)
def test_oauth_mode_fails_closed_without_a_request_token(context, exchanged, monkeypatch):
    monkeypatch.setenv("INFLUENCERS_CLUB_API_KEY", "env-key")

    async def scenario():
        # Neither a token remembered from session start nor the env key may stand in.
        auth_context_var.set(authenticated("alice.1"))
        if context is not None:
            request_ctx.set(context)
        await InfluencersApiClient(request_token=_request_token)._resolve_token()

    with pytest.raises(ApiError) as err:
        asyncio.run(scenario())
    assert err.value.status == 401
    assert exchanged == []


def test_without_oauth_the_env_key_is_used(exchanged, monkeypatch):
    """No callback (stdio, or HTTP without OAuth): the env key is used, nothing is exchanged."""
    monkeypatch.setenv("INFLUENCERS_CLUB_API_KEY", "env-key")

    assert asyncio.run(InfluencersApiClient()._resolve_token()) == "env-key"
    assert exchanged == []


REPO_ROOT = Path(__file__).resolve().parents[1]
OAUTH_ENV = {
    "MCP_OAUTH_ENABLED": "true",
    "MCP_OAUTH_CLIENT_ID": "client",
    "MCP_OAUTH_CLIENT_SECRET": "secret",
    "OAUTH_RESOURCE_URL": RESOURCE,
}


@pytest.mark.parametrize(
    ("env", "wired", "stateless"),
    [
        ({}, False, False),
        ({"MCP_TRANSPORT": "http"}, False, True),
        ({"MCP_TRANSPORT": "http", **OAUTH_ENV}, True, True),
    ],
    ids=["stdio", "http-without-oauth", "http-with-oauth"],
)
def test_server_wiring_follows_the_deployment_mode(env, wired, stateless):
    """server.py imported fresh in each deployment mode.

    The client gets the request-token reader exactly when OAuth is on: without it,
    calls would go out on the shared env key instead of each user's token; with it
    but no OAuth, every call would be refused. And only the hosted server runs
    stateless: stdio keeps its session, HTTP must not depend on one.
    """
    inherited = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("MCP_", "OAUTH_", "INFLUENCERS_CLUB_"))
    }
    probe = (
        "from influencers_club_mcp import server; "
        "print(server.client._request_token is server._request_token, "
        "server.mcp.settings.stateless_http)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        env={**inherited, **env},
        capture_output=True,
        text=True,
        errors="replace",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[-2:] == [str(wired), str(stateless)]


class AdmitAll(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        return access(token)


def hosted_server(stateless: bool = False) -> FastMCP:
    """A server wired like hosted mode: bearer auth on every request."""
    server = FastMCP(
        "request-token-test",
        stateless_http=stateless,
        token_verifier=AdmitAll(),
        auth=AuthSettings(issuer_url="https://auth.test", resource_server_url=RESOURCE),
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    client = InfluencersApiClient(request_token=_request_token)

    @server.tool()
    async def dashboard_token() -> str:
        return await client._resolve_token()

    return server


async def post(
    http: httpx.AsyncClient, token: str, message: dict, session: str | None = None
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
    if session is not None:
        headers["Mcp-Session-Id"] = session
    response = await http.post("/mcp", json=message, headers=headers)
    response.raise_for_status()
    return response


async def open_session(http: httpx.AsyncClient, token: str) -> str | None:
    response = await post(http, token, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    })
    session = response.headers.get("mcp-session-id")  # a stateless server issues none
    await post(http, token, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session)
    return session


async def call_tool(http: httpx.AsyncClient, token: str, session: str | None) -> str:
    response = await post(http, token, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "dashboard_token", "arguments": {}},
    }, session)
    events = [line[len("data:"):] for line in response.text.splitlines() if line.startswith("data:")]
    result = json.loads(events[-1])["result"]
    assert not result.get("isError"), result
    return result["content"][0]["text"]


@pytest.mark.parametrize("stateless", [False, True], ids=["stateful", "stateless"])
def test_tool_calls_follow_token_rotation_within_a_session(exchanged, stateless):
    """End to end through the SDK's streamable-HTTP transport, in both session modes."""
    server = hosted_server(stateless)
    app = server.streamable_http_app()

    async def scenario():
        async with server.session_manager.run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://mcp.test") as http:
                alice = await open_session(http, "alice.1")
                bob = await open_session(http, "bob.1")
                assert await call_tool(http, "alice.2", alice) == "dashboard-alice.2"
                assert await call_tool(http, "bob.1", bob) == "dashboard-bob.1"
                assert await call_tool(http, "alice.3", alice) == "dashboard-alice.3"

    asyncio.run(scenario())
