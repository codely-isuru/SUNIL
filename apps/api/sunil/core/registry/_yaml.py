"""Internal helper: read and parse one registry file, failing closed.

Not part of the public `sunil.core.registry` surface (leading underscore)
— every domain loader (`agents.py`, `permissions.py`, …) uses this so a
missing file or a YAML syntax error becomes one named exception type
rather than a `FileNotFoundError` or `yaml.YAMLError` surfacing from deep
inside a loader.

Reading is synchronous and deliberately so: it happens once, at process
startup, never inside a request path — `ARCHITECTURE_V1.md` §3.2's "no
sync file I/O in a request path" rule governs `core/` at *runtime*, not
config loaded once before the app starts serving.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from sunil.core.registry.errors import RegistryFileError, RegistrySchemaError


def read_yaml(path: Path) -> dict[str, Any]:
    """Read and parse one `config/*.yaml` file into a `dict`.

    Raises `RegistryFileError` if the file cannot be read or is not valid
    YAML, and `RegistrySchemaError` if it parses but is empty or its top
    level is not a mapping.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryFileError(f"{path}: cannot read config file ({exc})") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RegistryFileError(f"{path}: not valid YAML ({exc})") from exc

    if data is None:
        raise RegistrySchemaError(f"{path}: file is empty")
    if not isinstance(data, dict):
        raise RegistrySchemaError(f"{path}: top level must be a mapping, got {type(data).__name__}")

    return data
