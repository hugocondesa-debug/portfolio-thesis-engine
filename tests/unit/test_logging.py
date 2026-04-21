"""Tests for shared.logging_."""

import pytest
import structlog

from portfolio_thesis_engine.shared.logging_ import get_logger, setup_logging


def test_setup_logging_idempotent() -> None:
    setup_logging()
    setup_logging()


def test_get_logger_exposes_standard_methods() -> None:
    setup_logging()
    log = get_logger("test.module")
    for method in ("debug", "info", "warning", "error"):
        assert callable(getattr(log, method))


def test_logger_emits_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging()
    log = get_logger("test.emit")
    log.info("hello", foo="bar", n=1)
    out = capsys.readouterr().out
    assert "hello" in out
    assert "foo" in out


def test_structlog_is_configured() -> None:
    setup_logging()
    assert structlog.is_configured()
