"""`config/capture.yaml` — training-data capture defaults per content kind,
with a per-project override (A-6, ADR-014, `ARCHITECTURE_V1.md` §13.2).

This module only loads and exposes the *configured* defaults. Deriving a
`CaptureDecision` — including `training_eligible`, which is derived, never
hand-set (§13.2) — is `db/capture.py`'s `resolve_capture()` (T2), which
reads this registry rather than the YAML file directly.

Named `sunil.core.registry.capture` — distinct from `sunil.db.capture`
(T2's persistence-layer resolver/writer), a different module under a
different package, so there is no import collision.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from sunil.core.registry._yaml import read_yaml
from sunil.core.registry.errors import RegistrySchemaError

_VALID_POLICIES = {"none", "metadata_only", "redacted_full", "full_local_only"}
_VALID_SENSITIVITIES = {"public", "internal", "confidential", "restricted"}
_VALID_RETENTION_CLASSES = {"transient", "standard", "long", "permanent"}


class CaptureKind(StrEnum):
    """The five content kinds §13.2 tabulates defaults for.
    `audit_events` deliberately has no kind here and never will — a
    capture policy must never suppress an audit row (§7.3.1)."""

    MESSAGE = "message"
    PLAN = "plan"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    MEMORY = "memory"


class CaptureDefaults(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capture_policy: str
    sensitivity: str
    retention_class: str


class CaptureRegistry:
    def __init__(
        self,
        defaults: dict[CaptureKind, CaptureDefaults],
        project_overrides: dict[str, dict[CaptureKind, CaptureDefaults]],
    ) -> None:
        self._defaults = defaults
        self._project_overrides = project_overrides

    def defaults_for(self, kind: CaptureKind, project_key: str | None = None) -> CaptureDefaults:
        """The configured defaults for `kind`, applying `project_key`'s
        override when one is configured. Never raises for an unrecognised
        project — an unconfigured project simply has no override
        (§13.2: "M1 ships exactly one project and the defaults below")."""
        if project_key is not None:
            override = self._project_overrides.get(project_key, {}).get(kind)
            if override is not None:
                return override
        return self._defaults[kind]

    def referenced_project_keys(self) -> set[str]:
        """Every project key named in `project_overrides` — startup
        cross-validation checks each against `config/projects.yaml`."""
        return set(self._project_overrides.keys())


def _parse_defaults_block(
    path: Path, block: dict[str, Any], *, context: str
) -> dict[CaptureKind, CaptureDefaults]:
    result: dict[CaptureKind, CaptureDefaults] = {}
    for kind_name, body in block.items():
        try:
            kind = CaptureKind(kind_name)
        except ValueError:
            raise RegistrySchemaError(
                f"{path}: {context} names an unknown content kind {kind_name!r}"
            ) from None

        if not isinstance(body, dict):
            raise RegistrySchemaError(f"{path}: {context}.{kind_name} must be a mapping")

        policy = body.get("capture_policy")
        sensitivity = body.get("sensitivity")
        retention_class = body.get("retention_class")

        if policy not in _VALID_POLICIES:
            raise RegistrySchemaError(
                f"{path}: {context}.{kind_name}.capture_policy={policy!r} invalid "
                f"(must be one of {sorted(_VALID_POLICIES)})"
            )
        if sensitivity not in _VALID_SENSITIVITIES:
            raise RegistrySchemaError(
                f"{path}: {context}.{kind_name}.sensitivity={sensitivity!r} invalid "
                f"(must be one of {sorted(_VALID_SENSITIVITIES)})"
            )
        if retention_class not in _VALID_RETENTION_CLASSES:
            raise RegistrySchemaError(
                f"{path}: {context}.{kind_name}.retention_class={retention_class!r} invalid "
                f"(must be one of {sorted(_VALID_RETENTION_CLASSES)})"
            )

        result[kind] = CaptureDefaults(
            capture_policy=policy, sensitivity=sensitivity, retention_class=retention_class
        )
    return result


def load_capture(config_dir: Path) -> CaptureRegistry:
    path = config_dir / "capture.yaml"
    raw = read_yaml(path)

    version = raw.get("version")
    if version != 1:
        raise RegistrySchemaError(f"{path}: expected version: 1, found {version!r}")

    defaults_raw = raw.get("defaults") or {}
    if not isinstance(defaults_raw, dict):
        raise RegistrySchemaError(f"{path}: 'defaults' must be a mapping")
    defaults = _parse_defaults_block(path, defaults_raw, context="defaults")

    missing = set(CaptureKind) - set(defaults.keys())
    if missing:
        raise RegistrySchemaError(
            f"{path}: missing defaults for content kind(s): {sorted(k.value for k in missing)}"
        )

    overrides_raw = raw.get("project_overrides") or {}
    if not isinstance(overrides_raw, dict):
        raise RegistrySchemaError(f"{path}: 'project_overrides' must be a mapping")

    project_overrides: dict[str, dict[CaptureKind, CaptureDefaults]] = {}
    for project_key, block in overrides_raw.items():
        if not isinstance(block, dict):
            raise RegistrySchemaError(f"{path}: project_overrides.{project_key} must be a mapping")
        project_overrides[project_key] = _parse_defaults_block(
            path, block, context=f"project_overrides.{project_key}"
        )

    return CaptureRegistry(defaults, project_overrides)
