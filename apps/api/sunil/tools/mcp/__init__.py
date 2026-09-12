"""MCP adapters — ADR-034's mapping in code.

One MCP **server** is one permission-matrix **tool** (its ``config/tools.yaml``
key: ``github_mcp``, ``n8n_mcp``); one MCP **tool** is one **operation** under
it. ``tools/list`` output is informative only: an operation is callable iff
SUNIL's own config declares it AND the permission matrix grants it, and the
server's self-describing annotations (``readOnlyHint`` and friends) never
participate in a decision.
"""
