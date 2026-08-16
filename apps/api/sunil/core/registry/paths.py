"""Resolving `SUNIL_CONFIG_DIR` (ADR-016) to a real directory on disk.

`Settings.sunil_config_dir` (`sunil/settings.py`, T1) defaults to the
*string* `"./config"` (`ARCHITECTURE_V1.md` §14.4). A relative path is
ambiguous about "relative to what": `scripts/dev-api.ps1` starts uvicorn
with its working directory at `apps/api`, and `pyproject.toml`'s pytest
config makes `apps/api` the natural directory to run the test suite from
too (§2.1) — but `config/` lives at the repository root, one level above
`apps/` (§2.2's tree). Resolving the documented default against the
*process* working directory would silently fail to find the very files
this package owns, every time the app or the test suite is run the
documented way.

Resolution order, mirroring how `sunil/settings.py` resolves `.env`
relative to itself rather than to the process's working directory:

1. An absolute path is used as-is (this is also the container path,
   `/app/config`, from ADR-016's read-only compose mount) — it must exist.
2. A relative path is tried against the current working directory first,
   so a developer who has already `cd`d to wherever they mean gets exactly
   what they typed.
3. Otherwise it is tried against the repository root, computed the same
   deterministic way regardless of where the process was started from.

Neither existing is a `RegistryFileError` — never a bare
`FileNotFoundError` surfacing from inside a YAML loader.
"""

from __future__ import annotations

from pathlib import Path

from sunil.core.registry.errors import RegistryFileError

# apps/api/sunil/core/registry/paths.py
#   -> registry -> core -> sunil -> api -> apps -> repo root.
# Mirrors sunil/settings.py's own `_REPO_ROOT` computation (parents[3] from
# apps/api/sunil/settings.py); this file sits two directories deeper.
_REPO_ROOT = Path(__file__).resolve().parents[5]


def repo_root() -> Path:
    """The repository root, computed independently of the process's
    working directory. Exposed so tests can assert the resolver actually
    finds the real `config/` directory this task ships."""
    return _REPO_ROOT


def resolve_config_dir(configured: str | Path) -> Path:
    """Turn a configured `SUNIL_CONFIG_DIR` value into an existing directory.

    Raises `RegistryFileError` if no candidate exists.
    """
    configured_path = Path(configured)

    if configured_path.is_absolute():
        if configured_path.is_dir():
            return configured_path
        raise RegistryFileError(f"SUNIL_CONFIG_DIR {configured!r} does not exist (absolute path)")

    cwd_candidate = Path.cwd() / configured_path
    if cwd_candidate.is_dir():
        return cwd_candidate.resolve()

    repo_root_candidate = _REPO_ROOT / configured_path
    if repo_root_candidate.is_dir():
        return repo_root_candidate.resolve()

    raise RegistryFileError(
        f"SUNIL_CONFIG_DIR {configured!r} resolves to neither "
        f"{cwd_candidate} nor {repo_root_candidate}"
    )
