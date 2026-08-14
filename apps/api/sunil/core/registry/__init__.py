"""Configuration registries (T3): typed loaders for the six `config/*.yaml`
files — `agents.yaml`, `permissions.yaml`, `projects.yaml`, `models.yaml`,
`tools.yaml`, `capture.yaml` — cross-validated as one unit at startup
(ADR-016, `docs/M1_BUILD_PLAN.md` T3).

Import from here rather than from the individual submodules where
possible: `load_registries(settings.sunil_config_dir)` is the one call
every other lane (T6, T7, T8, T9, T10) needs.

An unknown agent, tool, model or project fails *closed* as one of the
named errors below — never as a bare `KeyError` — so a caller can tell
"the registry rejected this identifier" apart from "I indexed a dict
wrong".
"""

from __future__ import annotations

from sunil.core.registry.agents import AgentDefinition, AgentRegistry
from sunil.core.registry.capture import CaptureDefaults, CaptureKind, CaptureRegistry
from sunil.core.registry.errors import (
    RegistryCrossValidationError,
    RegistryError,
    RegistryFileError,
    RegistrySchemaError,
    UnknownAgentError,
    UnknownCapabilityError,
    UnknownModelError,
    UnknownOperationError,
    UnknownProjectError,
    UnknownToolError,
)
from sunil.core.registry.loader import Registries, load_registries, validate_cross_references
from sunil.core.registry.model_catalogue import (
    CapabilityDefinition,
    ModelDefinition,
    ModelRegistry,
)
from sunil.core.registry.permissions import PermissionRegistry
from sunil.core.registry.projects import (
    UNKNOWN_PROJECT_KEY,
    GithubCoordinates,
    ProjectDefinition,
    ProjectRegistry,
)
from sunil.core.registry.tools import ToolDefinition, ToolOperationDefinition, ToolRegistry

__all__ = [
    "UNKNOWN_PROJECT_KEY",
    "AgentDefinition",
    "AgentRegistry",
    "CapabilityDefinition",
    "CaptureDefaults",
    "CaptureKind",
    "CaptureRegistry",
    "GithubCoordinates",
    "ModelDefinition",
    "ModelRegistry",
    "PermissionRegistry",
    "ProjectDefinition",
    "ProjectRegistry",
    "Registries",
    "RegistryCrossValidationError",
    "RegistryError",
    "RegistryFileError",
    "RegistrySchemaError",
    "ToolDefinition",
    "ToolOperationDefinition",
    "ToolRegistry",
    "UnknownAgentError",
    "UnknownCapabilityError",
    "UnknownModelError",
    "UnknownOperationError",
    "UnknownProjectError",
    "UnknownToolError",
    "load_registries",
    "validate_cross_references",
]
