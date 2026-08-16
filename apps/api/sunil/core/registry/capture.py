"""`config/capture.yaml` — training-data capture defaults per content kind,
with a per-project override (A-6, ADR-014 + Amendment 1,
`ARCHITECTURE_V1.md` §13.2, A-18).

**This module owns the only string -> enum conversion for the capture
vocabulary** (ADR-014 Amendment 1 point 4). YAML strings become
`sunil.capture.CaptureRule` values here, refusing to boot on an unknown
value — exactly like every other registry (§10.2). Downstream code never
sees a plain string for a capture policy/sensitivity/retention class,
only `sunil.capture`'s typed enums and `CaptureRule`. Neither `core/` nor
`db/` may define a second copy of the vocabulary itself — that lives in
`sunil/capture.py`, a leaf module this one imports and nothing else does
for the enum definitions.

Deriving a `CaptureDecision` — including `training_eligible`, which is
derived, never hand-set (§13.2) — is `db/capture.py`'s `resolve_capture()`
(T2), which reads this registry's `dict[CaptureKind, CaptureRule]` rather
than the YAML file directly. `overrides_for()` below returns exactly the
`Mapping[CaptureKind, CaptureRule]` shape that function's `overrides`
parameter accepts, so the persistence layer passes this straight through
with no translation (Amendment 1 point 3: "no plain strings cross").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sunil.capture import CaptureKind, CapturePolicy, CaptureRule, RetentionClass, Sensitivity
from sunil.core.registry._yaml import read_yaml
from sunil.core.registry.errors import RegistrySchemaError


def _convert_kind(path: Path, kind_name: str, *, context: str) -> CaptureKind:
    try:
        return CaptureKind(kind_name)
    except ValueError:
        raise RegistrySchemaError(
            f"{path}: {context} names an unknown content kind {kind_name!r} "
            f"(must be one of {sorted(k.value for k in CaptureKind)})"
        ) from None


def _convert_policy(path: Path, value: Any, *, context: str) -> CapturePolicy:
    try:
        return CapturePolicy(value)
    except ValueError:
        raise RegistrySchemaError(
            f"{path}: {context}.capture_policy={value!r} invalid "
            f"(must be one of {sorted(p.value for p in CapturePolicy)})"
        ) from None


def _convert_sensitivity(path: Path, value: Any, *, context: str) -> Sensitivity:
    try:
        return Sensitivity(value)
    except ValueError:
        raise RegistrySchemaError(
            f"{path}: {context}.sensitivity={value!r} invalid "
            f"(must be one of {sorted(s.value for s in Sensitivity)})"
        ) from None


def _convert_retention_class(path: Path, value: Any, *, context: str) -> RetentionClass:
    try:
        return RetentionClass(value)
    except ValueError:
        raise RegistrySchemaError(
            f"{path}: {context}.retention_class={value!r} invalid "
            f"(must be one of {sorted(r.value for r in RetentionClass)})"
        ) from None


class CaptureRegistry:
    def __init__(
        self,
        defaults: dict[CaptureKind, CaptureRule],
        project_overrides: dict[str, dict[CaptureKind, CaptureRule]],
    ) -> None:
        self._defaults = defaults
        self._project_overrides = project_overrides

    def defaults_for(self, kind: CaptureKind, project_key: str | None = None) -> CaptureRule:
        """The configured rule for `kind`, applying `project_key`'s
        override when one is configured. Never raises for an unrecognised
        project — an unconfigured project simply has no override
        (§13.2: "M1 ships exactly one project and the defaults below")."""
        if project_key is not None:
            override = self._project_overrides.get(project_key, {}).get(kind)
            if override is not None:
                return override
        return self._defaults[kind]

    def overrides_for(self, project_key: str) -> dict[CaptureKind, CaptureRule]:
        """The full override mapping for one project (empty if none is
        configured) — exactly the `Mapping[CaptureKind, CaptureRule]`
        shape `db/capture.py`'s `resolve_capture(overrides=...)` accepts
        (ADR-014 Amendment 1 point 3), so a caller passes this straight
        through with no translation."""
        return dict(self._project_overrides.get(project_key, {}))

    def referenced_project_keys(self) -> set[str]:
        """Every project key named in `project_overrides` — startup
        cross-validation checks each against `config/projects.yaml`."""
        return set(self._project_overrides.keys())


def _parse_rule_block(
    path: Path, block: dict[str, Any], *, context: str
) -> dict[CaptureKind, CaptureRule]:
    result: dict[CaptureKind, CaptureRule] = {}
    for kind_name, body in block.items():
        kind = _convert_kind(path, kind_name, context=context)
        if not isinstance(body, dict):
            raise RegistrySchemaError(f"{path}: {context}.{kind_name} must be a mapping")
        rule_context = f"{context}.{kind_name}"
        result[kind] = CaptureRule(
            capture_policy=_convert_policy(path, body.get("capture_policy"), context=rule_context),
            sensitivity=_convert_sensitivity(path, body.get("sensitivity"), context=rule_context),
            retention_class=_convert_retention_class(
                path, body.get("retention_class"), context=rule_context
            ),
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
    defaults = _parse_rule_block(path, defaults_raw, context="defaults")

    missing = set(CaptureKind) - set(defaults.keys())
    if missing:
        raise RegistrySchemaError(
            f"{path}: missing defaults for content kind(s): {sorted(k.value for k in missing)}"
        )

    overrides_raw = raw.get("project_overrides") or {}
    if not isinstance(overrides_raw, dict):
        raise RegistrySchemaError(f"{path}: 'project_overrides' must be a mapping")

    project_overrides: dict[str, dict[CaptureKind, CaptureRule]] = {}
    for project_key, block in overrides_raw.items():
        if not isinstance(block, dict):
            raise RegistrySchemaError(f"{path}: project_overrides.{project_key} must be a mapping")
        project_overrides[project_key] = _parse_rule_block(
            path, block, context=f"project_overrides.{project_key}"
        )

    return CaptureRegistry(defaults, project_overrides)
