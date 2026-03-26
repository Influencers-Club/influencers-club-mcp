"""Influencers Club MCP Server."""

from .server import mcp

__all__ = ["mcp"]


def main():
    """Entry point that starts the upload server AND the MCP server."""
    from .upload_server import start_upload_server
    start_upload_server()
    mcp.run()
