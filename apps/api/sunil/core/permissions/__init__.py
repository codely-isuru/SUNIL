"""The permission engine (T7): `ALLOW / DENY / ASK_USER` decision function.

`ARCHITECTURE_V1.md` §9.2, FR-120/121, ADR-000 Q4. Import `decide()`,
`decide_with()`, `Decision` and `PermissionResult` from here.
"""

from __future__ import annotations

from sunil.core.permissions.engine import Decision, PermissionResult, decide, decide_with

__all__ = ["Decision", "PermissionResult", "decide", "decide_with"]
