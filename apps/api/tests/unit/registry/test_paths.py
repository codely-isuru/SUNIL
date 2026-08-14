"""`sunil.core.registry.paths` — resolving `SUNIL_CONFIG_DIR` (ADR-016)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sunil.core.registry.errors import RegistryFileError
from sunil.core.registry.paths import repo_root, resolve_config_dir


def test_absolute_existing_directory_resolves_to_itself(tmp_path: Path) -> None:
    assert resolve_config_dir(str(tmp_path)) == tmp_path


def test_absolute_missing_directory_fails_closed() -> None:
    with pytest.raises(RegistryFileError):
        resolve_config_dir("C:/definitely/not/a/real/path/xyz")


def test_relative_path_prefers_the_current_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "my_config").mkdir()
    monkeypatch.chdir(tmp_path)

    resolved = resolve_config_dir("./my_config")

    assert resolved == (tmp_path / "my_config").resolve()


def test_default_relative_value_falls_back_to_the_repository_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Settings.sunil_config_dir` defaults to the literal string
    `"./config"` (§14.4), but `scripts/dev-api.ps1` and the pytest suite
    both run with a working directory under `apps/api` — one level below
    where `config/` actually lives (§2.2's tree). This is the case that
    makes the documented dev workflow actually find T3's files."""
    monkeypatch.chdir(tmp_path)  # nothing named "config" here

    resolved = resolve_config_dir("./config")

    assert resolved == (repo_root() / "config").resolve()


def test_relative_path_that_resolves_nowhere_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RegistryFileError):
        resolve_config_dir("./no-such-directory-anywhere")


def test_repo_root_actually_contains_the_committed_config_directory() -> None:
    """Proves `repo_root()` is not just internally consistent but points at
    the real checkout — i.e. that T3's six files really do land where
    every other lane will look for them."""
    assert (repo_root() / "config" / "agents.yaml").is_file()
