"""Tool adapters (`sunil.tools.*`) — one subpackage per external system.

**Only `sunil/core/tool_framework/` may import from here** (DC-10,
enforced by T19's AST-walking import-boundary test,
`test_only_the_tool_framework_may_import_a_tool_adapter`). An agent or
the orchestrator never holds a reference to an adapter directly; the
Tool Manager is the sole caller.
"""

from __future__ import annotations
