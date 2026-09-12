"""Config registries — `config/*.yaml`, loaded once at boot (ADR-016).

The spine loads exactly two files: `agents.yaml` (which agent may reach which
tool operation) and `projects.yaml`. `models.yaml` is Stream B's, `tools.yaml`
and `permissions.yaml` are Stream A's — each stream loads its own, so no file has
two parsers.

Config is **mounted, never baked** (ADR-016) and cross-validated as one unit at
startup: a broken edit refuses the boot instead of failing on the first request
that happens to touch the bad part.
"""

from sunil.core.registry.loader import (
    AgentDefinition,
    ProjectDefinition,
    Registries,
    RegistryError,
    load_registries,
)

__all__ = [
    "AgentDefinition",
    "ProjectDefinition",
    "Registries",
    "RegistryError",
    "load_registries",
]
