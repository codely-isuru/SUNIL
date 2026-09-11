"""The permission engine — ``agent × tool × operation`` → ALLOW/ASK_USER/DENY.

M1's shape verbatim (ARCHITECTURE_V2 §2: "engine.py — M1 shape verbatim
(structural default-deny)"), returning C1 §2.2's ``PermissionResult`` so the
Tool Manager's injected ``PermissionHook`` seam is satisfied without a second
result type.
"""
