"""C1 adapter implementations (Stream A).

``github/`` is the native, read-only GitHub tool ported from M1; ``mcp/`` holds
the two MCP adapters (stdio child process, streamable HTTP). Nothing here may
bypass ``core/tool_framework``'s chokepoint: adapters expose operations and
execute them, and the permission decision, approval parking, auditing and the
untrusted-results posture all happen in the manager (C1 §1).
"""
