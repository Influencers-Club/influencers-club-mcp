import contextlib
import logging
import sys

from mcp.server.fastmcp import FastMCP

from influencers_club_mcp.log_config import configure_logging


@contextlib.contextmanager
def bare_root_logger():
    """Yield the root logger with no handlers, restoring it afterwards.

    pytest attaches its own capture handlers to the root logger, which would make
    configure_logging() (rightly) leave logging alone.
    """
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    root.handlers.clear()
    try:
        yield root
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def test_defaults_to_info_on_stderr(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    with bare_root_logger() as root:
        assert configure_logging() == "INFO"
        assert root.level == logging.INFO
        [handler] = root.handlers
        assert type(handler) is logging.StreamHandler
        assert handler.stream is sys.stderr


def test_level_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", " debug ")
    with bare_root_logger() as root:
        assert configure_logging() == "DEBUG"
        assert root.level == logging.DEBUG


def test_unknown_level_falls_back_to_info(monkeypatch, capsys):
    monkeypatch.setenv("LOG_LEVEL", "verbose")
    with bare_root_logger() as root:
        assert configure_logging() == "INFO"
        assert root.level == logging.INFO
    assert "Unknown LOG_LEVEL 'verbose'; using INFO" in capsys.readouterr().err


def test_fastmcp_keeps_records_on_one_line(monkeypatch, capsys):
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    with bare_root_logger() as root:
        level = configure_logging()
        [ours] = root.handlers
        FastMCP("test", log_level=level)
        assert root.handlers == [ours]  # FastMCP's line-wrapping handler stayed out
        logging.getLogger("influencers_club_mcp.test").info("x" * 300)
    assert "INFO influencers_club_mcp.test: " + "x" * 300 + "\n" in capsys.readouterr().err


def test_existing_configuration_is_left_alone(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    with bare_root_logger() as root:
        existing = logging.NullHandler()
        root.addHandler(existing)
        root.setLevel(logging.WARNING)
        configure_logging()
        assert root.handlers == [existing]
        assert root.level == logging.WARNING
