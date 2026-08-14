"""Deterministic core: orchestrator, registries, trace, audit, permissions.

`sunil.core` must never import `sunil.api` (ARCHITECTURE_V1.md §3.1) — the
orchestrator is invoked from an HTTP route today and from the scheduler in
M10, so it must not be coupled to a `Request`.
"""
