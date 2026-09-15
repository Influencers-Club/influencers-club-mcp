"""A dashboard outage during introspection is a 503, not a 401.

The SDK answers 401 whenever verify_token gives no token back, which tells the
client to re-authenticate. That is right when the dashboard says the token is
inactive and wrong when the dashboard could not be asked at all.
"""

import asyncio

import httpx
import pytest
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import LATEST_PROTOCOL_VERSION

from influencers_club_mcp.auth import ICTokenVerifier, IntrospectionUnavailableMiddleware
from influencers_club_mcp.server import _FastMCP

DASHBOARD = "https://dashboard.test"
RESOURCE = "https://mcp.test/mcp"
_RealAsyncClient = httpx.AsyncClient

INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": LATEST_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}


def hosted_server(token_verifier=None) -> _FastMCP:
    """The server as hosted mode builds it: bearer auth on every request when a verifier is given."""
    kwargs = {}
    if token_verifier is not None:
        kwargs = {
            "token_verifier": token_verifier,
            "auth": AuthSettings(issuer_url="https://auth.test", resource_server_url=RESOURCE),
        }
    return _FastMCP(
        "introspection-test",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        **kwargs,
    )


def initialize_with(introspect, monkeypatch) -> httpx.Response:
    """Open a session against a server whose introspection endpoint behaves like `introspect`."""
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _RealAsyncClient(transport=httpx.MockTransport(introspect), **kw),
    )
    server = hosted_server(ICTokenVerifier(DASHBOARD, "client", "secret", RESOURCE, []))
    app = server.streamable_http_app()

    async def scenario():
        async with server.session_manager.run():
            transport = httpx.ASGITransport(app=app)
            async with _RealAsyncClient(transport=transport, base_url="http://mcp.test") as http:
                return await http.post(
                    "/mcp",
                    json=INITIALIZE,
                    headers={"Authorization": "Bearer tok", "Accept": "application/json, text/event-stream"},
                )

    return asyncio.run(scenario())


def unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused")


def answering(status: int, **body):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body) if body else httpx.Response(status, text="<html>")

    return handler


@pytest.mark.parametrize(
    "introspect",
    [unreachable, answering(500), answering(403), answering(200)],
    ids=["unreachable", "dashboard-500", "blocked-403", "not-json"],
)
def test_no_verdict_is_a_503_not_a_challenge(introspect, monkeypatch):
    response = initialize_with(introspect, monkeypatch)

    assert response.status_code == 503
    assert response.headers["retry-after"]
    assert "www-authenticate" not in response.headers  # nothing to re-authenticate for
    assert response.json()["error"] == "temporarily_unavailable"


def test_inactive_token_is_still_a_401_challenge(monkeypatch):
    response = initialize_with(answering(200, active=False), monkeypatch)

    assert response.status_code == 401
    assert "www-authenticate" in response.headers


def test_active_token_is_admitted(monkeypatch):
    response = initialize_with(answering(200, active=True, aud=RESOURCE, sub="user"), monkeypatch)

    assert response.status_code == 200


def test_middleware_is_wired_exactly_when_a_verifier_is():
    with_auth = hosted_server(ICTokenVerifier(DASHBOARD, "client", "secret", RESOURCE, []))
    without_auth = hosted_server()

    def wired(server: _FastMCP) -> bool:
        return any(m.cls is IntrospectionUnavailableMiddleware for m in server.streamable_http_app().user_middleware)

    assert wired(with_auth)
    assert not wired(without_auth)
