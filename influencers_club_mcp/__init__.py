"""Influencers Club MCP Server."""

import logging
import os

from .server import mcp

__all__ = ["mcp"]

logger = logging.getLogger(__name__)


def main():
    """Entry point.

    Transport is selected via MCP_TRANSPORT:
      - unset / "stdio" (default): local stdio + the localhost upload server.
      - "http" / "streamable-http": remote HTTP transport, no upload server.
    """
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()

    if transport in ("http", "streamable-http"):
        # Remote hosted mode (Phase 3 — paired with OAuth on the dashboard).
        # The upload server is intentionally NOT started: localhost file flows
        # have no meaning when the MCP runs on shared infra.
        logger.info("Starting in streamable-http mode")
        mcp.run(transport="streamable-http")
        return

    if transport != "stdio":
        logger.warning("Unknown MCP_TRANSPORT='%s', falling back to stdio", transport)

    # Local mode: keep the existing behaviour exactly.
    from .upload_server import start_upload_server
    start_upload_server()
    mcp.run()
