"""SUNIL's own view of an MCP operation — the authoritative one (ADR-034).

``read_only``, ``timeout_s`` and the params model come from
``config/tools.yaml`` and NEVER from the server's self-description (C1 §2's
``ToolOperation`` docstring, ADR-034 decision 3). This dataclass is what a
loader produces and what an adapter is constructed with, so there is no code
path in which a server's ``inputSchema`` or ``readOnlyHint`` becomes SUNIL's
answer to those questions.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


@dataclass(frozen=True)
class McpOperationConfig:
    """One configured operation on one MCP server.

    ``name`` is BOTH the permission-matrix operation and the MCP tool name
    (ADR-034's mapping is 1:1 by name, so ``github_mcp.issues_close`` needs no
    translation table that could drift).
    """

    name: str
    params_model: type[BaseModel]
    read_only: bool
    timeout_s: float

    def __post_init__(self) -> None:
        # C1 §2 / §26.8: every params_model uses extra="forbid". Enforced here
        # because this is the one place a model becomes an operation: a model
        # that silently accepts unknown keys would let a plan smuggle arguments
        # past the validation the args_hash is computed over.
        if self.params_model.model_config.get("extra") != "forbid":
            raise ValueError(
                f"{self.name}: params_model {self.params_model.__name__} must set "
                'extra="forbid" (C1 §2)'
            )
        if self.timeout_s <= 0:
            raise ValueError(f"{self.name}: timeout_s must be positive")
