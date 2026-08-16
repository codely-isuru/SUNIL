"""The Tool Framework (T8): `ToolManager.execute()` and the adapter
primitives every `sunil.tools.*` package implements against.

`ARCHITECTURE_V1.md` §9.3, §10, §26.8. This is the **only** package
permitted to import `sunil.tools.*` (DC-10, enforced by T19's AST-walking
import-boundary test) — a tool adapter is never called directly by an
agent or the orchestrator.
"""

from __future__ import annotations
