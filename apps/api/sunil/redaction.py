"""Secret redaction — a mechanism, not a promise (ADR-006; C5 §3).

The claim being enforced: *no secret value appears in any prompt sent to a
model, any persisted log, any `audit_events.detail`, any trace detail or any
error message.* That is a statement about runtime behaviour, so it is enforced by
code on every write path, not by a convention engineers are asked to remember.

Two independent layers, both real:

1. **A value registry.** Every loaded secret's raw value is registered once
   (`register()` / `register_secrets_from_settings()`), and any occurrence of it
   in any string becomes `«redacted:<name>»`.
2. **Key-name and high-signal pattern redaction** (`scrub()`), which catches a
   secret that was *never* registered — C5 §3's invalid bearer token is exactly
   that case: it is attacker-supplied, so it is in no registry, and it is the
   value most worth not logging. `authorization`, `cookie`, `token`, `api_key`,
   `secret`, `password` keys have their values replaced outright, and
   `Bearer …`/`sk-ant-…`/`gh[pousr]_…` shapes are matched anywhere in text.

**`scrub()`'s type coverage is total, not an allowlist.** `str`, `dict`, plain
`list`/`tuple` and a few secret-incapable scalars are handled structurally, so
JSON shape survives. **Everything else — an exception, a dataclass, a Pydantic
model, a `NamedTuple` whose own privacy-aware `__repr__` a JSON renderer would
bypass, any custom object — is coerced through `repr()` and scrubbed.** An
`isinstance` dispatch that returns an unmatched value unchanged is not a
redaction mechanism; it is an allowlist with a silent passthrough default, and
the unmatched case is precisely where a secret survives. (This is a recorded
backend lesson from M1, kept deliberately.)

Where this is wired, so it cannot be silently missed:

* `scrub_processor` is a hard-wired, non-optional part of `sunil.logging`'s base
  processor chain (never a list callers append to — see that module).
* `core/audit/writer.py` scrubs `summary` and `detail` before every
  `audit_events` insert, unconditionally.
* `core/audit/tool_calls.py` scrubs `params_redacted` before the `tool_calls`
  insert; a provider lane must do the same for `llm_calls`.
* `register_secrets_from_settings()` runs once, in `sunil.main`'s lifespan.

Redaction is the SECOND line. The first is structural: secrets are never
assembled into prompt text, and header values are never inputs to a logging call
(C5 §3's load-bearing rule). If `scrub()` is ever seen actually redacting
something out of a persisted row in production, that is a defect upstream — not
evidence the control is working as intended.
"""

from __future__ import annotations

import re
import threading
from typing import Any

_KEY_NAME_PATTERN = re.compile(
    r"(api[_-]?key|apikey|authorization|token|secret|password|cookie)", re.IGNORECASE
)

_HIGH_SIGNAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer [A-Za-z0-9._-]{20,}"),
)

_KEY_REDACTED_PLACEHOLDER = "«redacted»"

# Types that structurally cannot carry a secret and are safe to pass through.
# Deliberately short: anything not here, and not handled structurally above it,
# falls through to the string-coercing fail-safe path.
_SAFE_SCALAR_TYPES: tuple[type, ...] = (bool, int, float, complex, type(None))

# Ignore anything shorter than this: redacting a 2-3 character value would
# corrupt unrelated text, and ADR-006 does not intend that.
_MIN_REGISTERABLE_LENGTH = 4

_registry_lock = threading.Lock()
_registry: dict[str, str] = {}  # raw secret value -> human-readable name


def register(value: str, *, name: str = "secret") -> None:
    """Register a secret's raw value for redaction. Idempotent."""
    if not value or len(value) < _MIN_REGISTERABLE_LENGTH:
        return
    with _registry_lock:
        _registry[value] = name


def register_secrets_from_settings(settings: Any) -> None:
    """Register every §5 secret from a `sunil.settings.Settings` instance.

    Kept generic over `settings: Any` rather than importing `Settings`, so this
    module has no import-time dependency on settings and `settings.py` can
    import it later without a cycle. Called once, from `sunil.main`'s lifespan,
    **before** anything else can log or persist.

    C5 §3's defence-in-depth clause names `SUNIL_SERVICE_TOKEN` and
    `SESSION_SECRET` specifically; the rest of §5's secret rows are registered on
    the same principle. An unset optional secret has nothing to register.
    """
    _register_optional(getattr(settings, "session_secret", None), "session_secret")
    _register_optional(getattr(settings, "sunil_service_token", None), "sunil_service_token")
    _register_optional(getattr(settings, "database_url", None), "database_url")
    _register_optional(getattr(settings, "github_token", None), "github_token")
    _register_optional(getattr(settings, "anthropic_api_key", None), "anthropic_api_key")
    _register_optional(getattr(settings, "openai_api_key", None), "openai_api_key")
    _register_optional(
        getattr(settings, "litellm_virtual_key_default", None), "litellm_virtual_key_default"
    )
    _register_optional(
        getattr(settings, "sunil_n8n_mcp_auth_token", None), "sunil_n8n_mcp_auth_token"
    )


def _register_optional(secret: Any, name: str) -> None:
    """`SecretStr | None` -> registered, or nothing. A bare `None` has no
    `.get_secret_value()` at all, so the unwrap itself has to be guarded."""
    if secret is None:
        return
    getter = getattr(secret, "get_secret_value", None)
    register(getter() if getter is not None else str(secret), name=name)


def _redact_registered_values(text: str) -> str:
    with _registry_lock:
        items = list(_registry.items())
    for value, name in items:
        if value and value in text:
            text = text.replace(value, f"«redacted:{name}»")
    return text


def _redact_high_signal_patterns(text: str) -> str:
    for pattern in _HIGH_SIGNAL_PATTERNS:
        text = pattern.sub(_KEY_REDACTED_PLACEHOLDER, text)
    return text


def _redact_string(text: str) -> str:
    return _redact_high_signal_patterns(_redact_registered_values(text))


def _safe_repr(obj: Any) -> str:
    """`repr(obj)`, never raising — a hostile or broken `__repr__` must not turn
    a redaction call on a logging path into an unhandled exception."""
    try:
        return repr(obj)
    except Exception:  # deliberately blind: a repr() failure must not propagate
        return f"<unrepresentable {type(obj).__name__}>"


def _is_plain_tuple(obj: Any) -> bool:
    """A bare `tuple`, safe to recurse into positionally. A `NamedTuple` (every
    one carries `_fields`) is excluded: it commonly has a privacy-aware
    `__repr__` that a JSON renderer serialising it as a positional array would
    bypass — which is how a NamedTuple's field leaked in the wild. NamedTuples
    take the string-coercing path instead, so their masking repr is what runs."""
    return isinstance(obj, tuple) and not hasattr(obj, "_fields")


def scrub(obj: Any) -> Any:
    """Recursively redact `obj`, returning a NEW structure — never mutating the
    original, so a caller still holding the reference cannot accidentally
    persist or log the unredacted version."""
    if isinstance(obj, str):
        return _redact_string(obj)
    if isinstance(obj, dict):
        return {
            key: (
                _KEY_REDACTED_PLACEHOLDER
                if _KEY_NAME_PATTERN.search(str(key))
                else scrub(value)
            )
            for key, value in obj.items()
        }
    if _is_plain_tuple(obj):
        return tuple(scrub(item) for item in obj)
    if isinstance(obj, list):
        return [scrub(item) for item in obj]
    if isinstance(obj, _SAFE_SCALAR_TYPES):
        return obj
    # Fail safe: every type not handled above is treated as unsafe, not as free
    # passage.
    return _redact_string(_safe_repr(obj))


def scrub_processor(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """A structlog processor: scrub the whole event dict before it is rendered.
    Wired into `sunil.logging`'s base chain, not appended by callers."""
    del logger, method_name
    return scrub(event_dict)


def reset_registry_for_tests() -> None:
    """Test-only: module-level state is shared across a pytest process, so one
    test's registered secret must not leak into another's assertions."""
    with _registry_lock:
        _registry.clear()
