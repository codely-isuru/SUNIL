"""The native GitHub tool (ported from M1 for V2's C1 chokepoint).

``adapter.GitHubAdapter`` implements C1 §2's ``ToolAdapter`` (``kind=NATIVE``,
``server_id=None``, lifecycle no-ops); ``projection.py`` — M1's code verbatim —
is the security component that shapes everything the adapter returns before it
can reach a model.

Kept alongside the ``github_mcp`` MCP server on purpose: ADR-034's consequence
list calls for a parity test asserting that the same permission triple produces
identical decisions and audit rows through a native adapter and an MCP one,
which proves the mapping preserved the M1 model. This is the native half.
"""

from __future__ import annotations
