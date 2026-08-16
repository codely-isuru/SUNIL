"""Named registry errors.

Registries are a security surface — `config/*.yaml` defines which agents,
tools, models and projects the system will act on (`docs/M1_BUILD_PLAN.md`
T3 "Watch") — not just plumbing. An unknown agent, tool, model or project
must fail *closed* as one of these named exceptions, never as a bare
`KeyError`: a caller (T7's permission engine, T8's tool manager, T9's plan
validator, T10's agent runner) needs to be able to catch "the registry
rejected this identifier" as its own category, distinct from "I made a
programming mistake indexing a dict".
"""

from __future__ import annotations


class RegistryError(Exception):
    """Base class for every failure this package raises. Catch this at
    startup to treat any config problem as one category and refuse to
    boot (ADR-016 §4)."""


class RegistryFileError(RegistryError):
    """A registry file is missing, unreadable, or is not valid YAML."""


class RegistrySchemaError(RegistryError):
    """A registry file parsed as YAML but its shape does not match the
    schema documented in `ARCHITECTURE_V1.md` (§9.2, §10.2, §4.4, §13.2) —
    a missing required key, a wrong type, an invalid enum value, or an
    unexpected extra key."""


class RegistryCrossValidationError(RegistryError):
    """One or more registries reference an entry that does not exist in
    another registry (`docs/M1_BUILD_PLAN.md` T3 "startup
    cross-validation"). Carries every mismatch found, not just the first,
    so one fix-and-restart cycle can close every gap instead of one per
    restart."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(problems))


class UnknownAgentError(RegistryError):
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__(f"no agent registered with id {agent_id!r}")


class UnknownToolError(RegistryError):
    def __init__(self, tool: str) -> None:
        self.tool = tool
        super().__init__(f"no tool registered with name {tool!r}")


class UnknownOperationError(RegistryError):
    def __init__(self, tool: str, operation: str) -> None:
        self.tool = tool
        self.operation = operation
        super().__init__(f"tool {tool!r} has no operation {operation!r}")


class UnknownProjectError(RegistryError):
    def __init__(self, project_key: str) -> None:
        self.project_key = project_key
        super().__init__(f"no project registered with key {project_key!r}")


class UnknownModelError(RegistryError):
    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        super().__init__(f"no model registered with id {model_id!r}")


class UnknownCapabilityError(RegistryError):
    def __init__(self, capability: str) -> None:
        self.capability = capability
        super().__init__(f"no capability registered with name {capability!r}")
