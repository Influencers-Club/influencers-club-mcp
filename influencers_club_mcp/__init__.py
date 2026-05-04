"""Influencers Club MCP Server."""

import os
import sys

from .server import mcp

__all__ = ["mcp"]


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
        print("[MCP] Starting in streamable-http mode", file=sys.stderr)
        mcp.run(transport="streamable-http")
        return

    if transport != "stdio":
        print(
            f"[MCP] Unknown MCP_TRANSPORT='{transport}', falling back to stdio",
            file=sys.stderr,
        )

    # Local mode: keep the existing behaviour exactly.
    from .upload_server import start_upload_server
    start_upload_server()
    mcp.run()
