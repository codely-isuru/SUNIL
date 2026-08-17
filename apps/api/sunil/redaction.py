"""Secret redaction — a mechanism, not a promise (ADR-006, §8.3, ET-10).

ET-10: *no secret value may appear in any prompt sent to the LLM or in any
persisted log for the request.* That is a claim about runtime behaviour,
so it is enforced by code that runs on every write path, not by a
convention engineers are asked to remember.

Two independent layers, both real:

1. **A value registry.** Every loaded secret's raw value is registered
   once (`register()`), and any occurrence of it anywhere in a string is
   replaced with `«redacted:<name>»`.
2. **Key-name and high-signal pattern redaction** (`scrub()`), which
   catches a secret that was *never* registered — a stray token pasted
   into a message, for instance — by looking at the shape of the value
   (`sk-ant-…`, `gh[pousr]_…`, `Bearer …`) or the name of the field it is
   stored under (`api_key`, `token`, `password`, `cookie`, ...).

**`scrub()`'s type coverage is total, not an allowlist.** `str`, `dict`,
plain `list`/`tuple` and a small set of secret-incapable scalars
(`bool`/`int`/`float`/`complex`/`None`) are handled structurally, so JSON
shape is preserved wherever possible. **Everything else — an exception
instance, a dataclass, a Pydantic model, a `NamedTuple` with its own
privacy-aware `__repr__` (`sqlalchemy.engine.URL` masks its password this
way, but a JSON renderer serialising it as a plain array bypasses that
`__repr__` entirely), a custom object with a secret-bearing `__repr__` —
is coerced through its string representation and scrubbed.** An
`isinstance` dispatch that returns an unmatched value unchanged is not a
redaction mechanism; it is an allowlist with a silent passthrough default,
and the unmatched case is exactly where a secret survives. Treating the
unmatched case as unsafe (scrub its text form) rather than as free passage
is the whole fix — see the backend_engineer memory lesson this bug
produced.

Secrets are never assembled into prompt text in the first place (§9.1) —
that is the primary control. Redaction is the second line, and the one
that is testable: if `scrub()` is ever seen actually redacting something
out of a persisted `llm_calls` row in production, that is a defect to fix
upstream, not evidence the control is working as intended (ADR-006's own
framing).

**Wiring, and who owns which call site (so this does not get silently
missed):**

- `scrub_processor` is a hard-wired part of `sunil.logging`'s base
  processor chain (this task, T4 — see that module for why it is baked
  into `configure_logging()` rather than a list callers append to).
- `core/audit/writer.py` (this task) calls `scrub()` on `detail` before
  every `audit_events` insert.
- **T6 and T8 must call `scrub()` themselves**, before their own
  `llm_calls.request_*`/`response_*` and `tool_calls.parameters`/`result`
  inserts (ADR-006) — this module provides the mechanism; it does not, and
  structurally cannot, reach into another lane's insert call site.
- **Registering the actual secret values** (`register_secrets_from_settings()`
  below) is called once at process startup, from `sunil.main`'s lifespan.
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

# Types that structurally cannot carry a secret on their own and are safe
# to pass through unchanged. Deliberately short — anything not in this
# list, and not a str/dict/list/plain-tuple handled structurally above it,
# falls through to the string-coercing fail-safe path below.
_SAFE_SCALAR_TYPES: tuple[type, ...] = (bool, int, float, complex, type(None))

# Ignore anything shorter than this: redacting a 2-3 character value would
# corrupt unrelated text, and ADR-006 does not intend that.
_MIN_REGISTERABLE_LENGTH = 4

_registry_lock = threading.Lock()
_registry: dict[str, str] = {}  # raw secret value -> a human-readable name


def register(value: str, *, name: str = "secret") -> None:
    """Register a secret's raw value for redaction.

    Called once per secret, at load time — see
    `register_secrets_from_settings()` for the M1 secret set. Idempotent:
    registering the same value twice just updates its name. `name` is
    optional (defaults to the generic `"secret"`) so an ad hoc registration
    of a value nobody has bothered to label still redacts correctly.
    """
    if not value or len(value) < _MIN_REGISTERABLE_LENGTH:
        return
    with _registry_lock:
        _registry[value] = name


def register_secrets_from_settings(settings: Any) -> None:
    """Register every M1 secret from a `sunil.settings.Settings` instance.

    Kept generic over `settings: Any` (rather than importing
    `sunil.settings.Settings`) so this module has no import-time
    dependency on settings — `sunil.settings` can import `sunil.redaction`
    later (e.g. from a lifespan hook) without a circular import.

    Called from `sunil.main`'s lifespan, once at startup.
    """
    register(settings.anthropic_api_key.get_secret_value(), name="anthropic_api_key")
    register(settings.github_token.get_secret_value(), name="github_token")
    # T23: the second provider's key is exactly as registrable as the
    # first's — §9.1 registers secrets "regardless of their value", not
    # only the ones a given milestone happens to call with.
    register(settings.openai_api_key.get_secret_value(), name="openai_api_key")
    register(settings.session_secret.get_secret_value(), name="session_secret")
    register(settings.owner_password.get_secret_value(), name="owner_password")
    # The password embedded in a Postgres DATABASE_URL, if any (ADR-006:
    # "including the password inside a Postgres DATABASE_URL"). SQLite's
    # default carries no credential; registering it is harmless (it is
    # simply never found in any string) — cheaper than parsing the URL to
    # decide.
    register(settings.database_url.get_secret_value(), name="database_url")


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
    text = _redact_registered_values(text)
    text = _redact_high_signal_patterns(text)
    return text


def _safe_repr(obj: Any) -> str:
    """`repr(obj)`, never raising — a hostile or broken `__repr__` must not
    turn a redaction call into an unhandled exception on a logging or
    persistence path."""
    try:
        return repr(obj)
    except Exception:  # deliberately blind: any repr() failure must not propagate
        return f"<unrepresentable {type(obj).__name__}>"


def _is_plain_tuple(obj: Any) -> bool:
    """A bare `tuple`, safe to recurse into positionally. A `NamedTuple`
    (detected by the `_fields` attribute every one carries) is excluded —
    it commonly has its own privacy-aware `__repr__`
    (`sqlalchemy.engine.URL` masks its password there), and a JSON
    renderer serialising it as a plain positional array bypasses that
    `__repr__` entirely, which is exactly how a NamedTuple's field leaked
    in the wild. NamedTuples fall through to the string-coercing fail-safe
    path instead, so their own masking `__repr__` is what runs.
    """
    return isinstance(obj, tuple) and not hasattr(obj, "_fields")


def scrub(obj: Any) -> Any:
    """Recursively redact `obj`. Returns a new structure; never mutates
    `obj` in place, so a caller that still holds the original reference
    cannot accidentally persist or log the unredacted version.

    - `str`: registered values and high-signal patterns are replaced.
    - `dict`: any key matching `_KEY_NAME_PATTERN` has its value replaced
      outright (regardless of type); every other value is scrubbed
      recursively.
    - plain `list` / plain `tuple`: every element scrubbed recursively,
      same container type preserved.
    - `bool` / `int` / `float` / `complex` / `None`: returned unchanged —
      these types cannot carry a secret string.
    - **anything else** (an exception, a dataclass, a Pydantic model, a
      `NamedTuple`, any custom object): coerced through `repr()` and
      scrubbed as a string. This is the fail-safe default a bare
      `isinstance` allowlist does not have — see the module docstring.
    """
    if isinstance(obj, str):
        return _redact_string(obj)
    if isinstance(obj, dict):
        return {
            key: (_KEY_REDACTED_PLACEHOLDER if _KEY_NAME_PATTERN.search(str(key)) else scrub(value))
            for key, value in obj.items()
        }
    if _is_plain_tuple(obj):
        return tuple(scrub(item) for item in obj)
    if isinstance(obj, list):
        return [scrub(item) for item in obj]
    if isinstance(obj, _SAFE_SCALAR_TYPES):
        return obj

    # Fail safe: every type not handled above — treated as unsafe, not as
    # free passage.
    return _redact_string(_safe_repr(obj))


def scrub_processor(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """A structlog processor: scrub the whole event dict before it is
    rendered. Wired into `sunil.logging.shared_processors`."""
    del logger, method_name
    return scrub(event_dict)


def reset_registry_for_tests() -> None:
    """Test-only: clear the registry so one test's registered secret can
    never leak into another test's assertions (module-level state is
    otherwise shared across the whole pytest process)."""
    with _registry_lock:
        _registry.clear()
