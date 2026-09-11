"""Fixtures for the integration suite only — see `tests/unit/conftest.py` for
why they are imported by name and not registered as a plugin."""

from tests.spine_harness import (  # noqa: F401 - re-exported as fixtures
    _clean_redaction_registry,
    build_settings,
    session_factory,
)
