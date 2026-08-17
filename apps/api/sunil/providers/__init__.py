"""LLM provider adapters (ADR-003).

`sunil.providers` is the **only** package permitted to `import anthropic`
(or any other vendor SDK) — FR-040's own acceptance criterion, checked by
T19's AST-walking import-boundary test and run on every merge (T21).
Everything else in SUNIL depends on `sunil.providers.base`'s `LLMProvider`
protocol and dataclasses, and on `sunil.core.routing`'s Model Router —
never on a vendor type or a vendor SDK call directly.
"""
