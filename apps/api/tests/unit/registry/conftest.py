"""Shared fixtures for `sunil.core.registry` unit tests.

Fixtures only — pytest injects these by directory scope, no import
statement needed. The YAML-document constants and the
`valid_config_files()`/`write_config_dir()` helper functions live in
`registry_helpers.py` instead, precisely so nothing here needs to be
*imported* by name (see that module's own docstring for why a cross-file
`from conftest import ...` is the pattern CI now blocks).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .registry_helpers import valid_config_files, write_config_dir


@pytest.fixture
def valid_config_dir(tmp_path: Path) -> Path:
    """A temp directory holding a complete, valid, mutually consistent set
    of the six registry files."""
    return write_config_dir(tmp_path, valid_config_files())
