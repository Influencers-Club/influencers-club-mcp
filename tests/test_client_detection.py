"""Which client is behind the current message.

Over stdio the session handled the client's initialize request, so the name it
gave there is known. Over stateless HTTP every request gets a fresh session that
never saw an initialize, so there is nothing to know and the answer is "".
"""

import asyncio

from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel.server import request_ctx
from mcp.shared.context import RequestContext
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import Implementation

from influencers_club_mcp.server import _get_mcp_client_name


def test_outside_any_message_the_client_is_unknown():
    assert _get_mcp_client_name() == ""


def test_stdio_uses_the_name_the_client_gave_at_initialize():
    """Through a real session, connected the way stdio connects one."""
    server = FastMCP("client-detection-test")

    @server.tool()
    async def who() -> str:
        return _get_mcp_client_name()

    async def scenario() -> str:
        async with create_connected_server_and_client_session(
            server, client_info=Implementation(name="claude-code", version="0")
        ) as client:
            result = await client.call_tool("who", {})
            return result.content[0].text

    assert asyncio.run(scenario()) == "claude-code"


class StatelessSession:
    """What a stateless HTTP session exposes: it never handled an initialize."""

    client_params = None


def test_a_stateless_session_has_no_client_name():
    token = request_ctx.set(
        RequestContext(request_id=1, meta=None, session=StatelessSession(), lifespan_context=None, request=None)
    )
    try:
        assert _get_mcp_client_name() == ""
    finally:
        request_ctx.reset(token)
