"""SUNIL's own view of an MCP operation — the authoritative one (ADR-034).

``read_only``, ``timeout_s`` and the params model come from
``config/tools.yaml`` and NEVER from the server's self-description (C1 §2's
``ToolOperation`` docstring, ADR-034 decision 3). This dataclass is what a
loader produces and what an adapter is constructed with, so there is no code
path in which a server's ``inputSchema`` or ``readOnlyHint`` becomes SUNIL's
answer to those questions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from pydantic import BaseModel


@dataclass(frozen=True)
class McpOperationConfig:
    """One configured operation on one MCP server.

    ``name`` is SUNIL's — the permission-matrix operation, the approval card, the
    audit row. ``server_tools`` is what that name is BOUND to on the wire
    (ADR-034 Amendment 1, ruling R16 part 3's naming law): SUNIL's vocabulary
    never tracks a vendor, so a vendor rename is absorbed here and nowhere else.

    The mapping used to be 1:1 by name, and still is by DEFAULT — an operation
    with no ``server_tool:`` binds to itself, so every pre-Amendment row keeps
    its meaning. It stopped being the only shape on 2026-09-16, when the capture
    of `github/github-mcp-server` v1.12.2 found `update_issue` renamed to
    `issue_write` (`docs/tasks/S3-github.md` §0).

    ``server_tools`` is a TUPLE because one governed operation may be a bounded
    COMPOSITION of more than one server tool (R16 part 3's ``merge_main``:
    ``create_pull_request`` then ``merge_pull_request``). The drift check
    verifies every entry.

    ``fixed_arguments`` are constants the ADAPTER supplies and a plan cannot
    (``issues_close`` → ``{method: update, state: closed}``). They may never
    collide with a field of ``params_model``: the ``args_hash`` an approval binds
    to is computed over that model, so a fixed argument able to overwrite
    ``issue_number`` would make "the owner approved closing issue 42" false while
    the card still said 42.
    """

    name: str
    params_model: type[BaseModel]
    read_only: bool
    timeout_s: float
    server_tools: tuple[str, ...] = ()
    fixed_arguments: Mapping[str, Any] = field(default_factory=dict)
    composition: str | None = None

    def __post_init__(self) -> None:
        if not self.server_tools:
            object.__setattr__(self, "server_tools", (self.name,))
        object.__setattr__(
            self, "fixed_arguments", MappingProxyType(dict(self.fixed_arguments))
        )
        collisions = sorted(set(self.fixed_arguments) & set(self.params_model.model_fields))
        if collisions:
            raise ValueError(
                f"{self.name}: fixed_arguments {collisions} collide with fields of "
                f"{self.params_model.__name__} — a constant that can overwrite a validated "
                "argument would break the args_hash an approval binds to (ADR-034 "
                "Amendment 1)"
            )
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
