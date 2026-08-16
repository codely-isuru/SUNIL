"""Fixtures for the T19 security suite — fixtures only.

Constants and gates live in `security_helpers.py` and are imported explicitly.
Nothing may import this module by name: that turns pytest's directory-scoped
fixture injection into an ordinary module import, which collides with every
other `conftest.py` collected in the same run. See `security_helpers.py`.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator

import pytest
from security_helpers import FAKE_ENV


@pytest.fixture
def fake_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Every required variable set to an obvious fake, `.env` bypassed."""
    for key, value in FAKE_ENV.items():
        monkeypatch.setenv(key, value)
    return dict(FAKE_ENV)


@pytest.fixture
def log_capture() -> Iterator[io.StringIO]:
    """Capture what the real structlog chain renders, formatter included."""
    from sunil.logging import configure_logging

    configure_logging(log_level="DEBUG", json_output=True)
    root = logging.getLogger()
    original = list(root.handlers)
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    if original:
        handler.setFormatter(original[0].formatter)
    root.handlers = [handler]
    try:
        yield buffer
    finally:
        root.handlers = original
