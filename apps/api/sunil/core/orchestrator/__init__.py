"""The Central Orchestrator (deterministic) — `ARCHITECTURE_V1.md` §1.2.

T9 owns the privileged gate in this package: `plan_schema.py`,
`plan_models.py`, `plan_validator.py`, `guards.py` — the five-layer chain
of ADR-004 plus its Amendment 1 runtime guard. `turn.py` (the 12-stage
pipeline) is T11b's build, in the same package, in another lane.
"""

from __future__ import annotations
