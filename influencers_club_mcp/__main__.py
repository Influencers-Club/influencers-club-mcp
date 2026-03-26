"""Allow running with `python -m influencers_club_mcp`."""

from .upload_server import start_upload_server

# Start the HTTP upload server (runs in a daemon thread)
start_upload_server()

from .server import mcp

mcp.run()
