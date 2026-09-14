"""Process-wide logging setup.

Everything logs through the standard ``logging`` module to stderr — never
stdout, which carries the MCP protocol in stdio mode.

Call ``configure_logging()`` before constructing ``FastMCP()``. FastMCP runs
``logging.basicConfig`` with a rich handler, which wraps long records across
several lines whenever stderr is not a terminal (a service log, a client's MCP
log file). ``basicConfig`` is a no-op once the root logger has a handler, so
configuring it here first keeps every record on one line.
"""

import logging
import os
import sys

# The level names FastMCP accepts (it hands them on to uvicorn, lower-cased).
_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def configure_logging() -> str:
    """Configure root logging from ``LOG_LEVEL`` and return the level name.

    ``LOG_LEVEL`` is case-insensitive and defaults to INFO; an unknown value
    falls back to INFO with a warning. A root logger that is already configured
    (by an embedding application or a test runner) is left untouched.
    """
    raw = os.environ.get("LOG_LEVEL") or "INFO"
    level = raw.strip().upper()
    known = level in _LEVELS
    if not known:
        level = "INFO"
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    if not known:
        logging.getLogger(__name__).warning("Unknown LOG_LEVEL %r; using INFO", raw)
    return level
