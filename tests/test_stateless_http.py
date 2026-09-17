"""Any instance can serve any request: the hosted server keeps no session state.

Behind a load balancer with no stickiness, a stateful streamable-HTTP session is
known only to the process that opened it: every request routed elsewhere is a
404 "Session not found", and every deploy drops every session. In stateless mode
the SDK builds a throwaway transport and session per request and issues no
Mcp-Session-Id, so nothing ties a client to an instance.
"""

import asyncio
import contextlib
import json

import httpx
import pytest
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import LATEST_PROTOCOL_VERSION

from influencers_club_mcp.server import _request_token

RESOURCE = "https://mcp.test/mcp"

INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": LATEST_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
CALL = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "token_seen", "arguments": {}}}


class AdmitAll(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        return AccessToken(token=token, client_id=token, scopes=[], expires_at=None, resource=RESOURCE)


def hosted_server(stateless: bool = True) -> FastMCP:
    """A server wired like hosted mode: bearer auth on every request."""
    server = FastMCP(
        "stateless-test",
        stateless_http=stateless,
        token_verifier=AdmitAll(),
        auth=AuthSettings(issuer_url="https://auth.test", resource_server_url=RESOURCE),
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @server.tool()
    async def token_seen() -> str:
        """The bearer the server's own request-token reader hands the API client."""
        return _request_token() or ""

    return server


def post(http: httpx.AsyncClient, token: str, message: dict, session: str | None = None):
    """The request coroutine; callers assert on the status themselves."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
    if session is not None:
        headers["Mcp-Session-Id"] = session
    return http.post("/mcp", json=message, headers=headers)


def tool_text(response: httpx.Response) -> str:
    assert response.status_code == 200, response.text
    events = [line[len("data:"):] for line in response.text.splitlines() if line.startswith("data:")]
    result = json.loads(events[-1])["result"]
    assert not result.get("isError"), result
    return result["content"][0]["text"]


def run(scenario, *servers: FastMCP) -> None:
    """Run scenario(*clients), one in-process HTTP client per server, session managers up."""

    async def main():
        async with contextlib.AsyncExitStack() as stack:
            clients = []
            for server in servers:
                app = server.streamable_http_app()
                await stack.enter_async_context(server.session_manager.run())
                clients.append(await stack.enter_async_context(
                    httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mcp.test")
                ))
            await scenario(*clients)

    asyncio.run(main())


@pytest.mark.parametrize("stateless", [True, False], ids=["stateless", "stateful"])
def test_only_a_stateful_server_issues_a_session_id(stateless):
    async def scenario(http):
        response = await post(http, "alice", INITIALIZE)
        assert response.status_code == 200
        assert ("mcp-session-id" in response.headers) is not stateless

    run(scenario, hosted_server(stateless))


def test_a_call_needs_no_initialize_on_the_instance_that_serves_it():
    """Two servers stand in for two instances behind the load balancer."""

    async def scenario(first, second):
        assert (await post(first, "alice", INITIALIZE)).status_code == 200
        assert tool_text(await post(second, "alice", CALL)) == "alice"

    run(scenario, hosted_server(), hosted_server())


def test_a_stateful_server_rejects_a_session_another_instance_opened():
    """The failure stateless mode removes; keeps the test above honest."""

    async def scenario(first, second):
        session = (await post(first, "alice", INITIALIZE)).headers["mcp-session-id"]
        assert (await post(second, "alice", CALL, session)).status_code == 404

    run(scenario, hosted_server(stateless=False), hosted_server(stateless=False))


def test_a_session_id_from_before_the_switch_is_ignored():
    """Clients mid-session during the deploy keep sending the id the old build issued."""

    async def scenario(http):
        assert tool_text(await post(http, "alice", CALL, session="issued-by-the-stateful-build")) == "alice"

    run(scenario, hosted_server())


def test_each_request_sees_its_own_token():
    """There is no session task left to inherit a stale token from."""

    async def scenario(http):
        assert tool_text(await post(http, "alice", CALL)) == "alice"
        assert tool_text(await post(http, "bob", CALL)) == "bob"
        assert tool_text(await post(http, "alice.rotated", CALL)) == "alice.rotated"

    run(scenario, hosted_server())
