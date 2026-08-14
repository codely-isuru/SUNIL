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

Secrets are never assembled into prompt text in the first place (§9.1) —
that is the primary control. Redaction is the second line, and the one
that is testable: if `scrub()` is ever seen actually redacting something
out of a persisted `llm_calls` row in production, that is a defect to fix
upstream, not evidence the control is working as intended (ADR-006's own
framing).

**Wiring, and who owns which call site (so this does not get silently
missed):**

- `redaction_processor` is registered as a structlog processor in
  `sunil.logging.shared_processors` (this task, T4 — see that module).
- `core/audit/writer.py` (this task) calls `scrub()` on `detail` before
  every `audit_events` insert.
- **T6 and T8 must call `scrub()` themselves**, before their own
  `llm_calls.request_*`/`response_*` and `tool_calls.parameters`/`result`
  inserts (ADR-006) — this module provides the mechanism; it does not, and
  structurally cannot, reach into another lane's insert call site.
- **Registering the actual secret values** (`register_secrets_from_settings()`
  below) must be called once at process startup, with the live `Settings`
  instance. T4's file-ownership does not extend to `sunil/main.py`'s
  startup sequence — that one-line call is for whoever next extends
  `create_app()` (T5) to add.
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

# Ignore anything shorter than this: redacting a 2-3 character value would
# corrupt unrelated text, and ADR-006 does not intend that.
_MIN_REGISTERABLE_LENGTH = 4

_registry_lock = threading.Lock()
_registry: dict[str, str] = {}  # raw secret value -> a human-readable name


def register(value: str, *, name: str) -> None:
    """Register a secret's raw value for redaction.

    Called once per secret, at load time — see
    `register_secrets_from_settings()` for the M1 secret set. Idempotent:
    registering the same value twice just updates its name.
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

    **Not called anywhere yet.** ADR-006 assigns this call to
    "`settings.py`, once at startup", but this task's file ownership does
    not extend to `sunil/main.py`'s startup sequence. Whoever next extends
    `create_app()` (T5) must call this once, e.g.:
    `redaction.register_secrets_from_settings(get_settings())`.
    """
    register(settings.anthropic_api_key.get_secret_value(), name="anthropic_api_key")
    register(settings.github_token.get_secret_value(), name="github_token")
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


def scrub(obj: Any) -> Any:
    """Recursively redact `obj`. Returns a new structure; never mutates
    `obj` in place, so a caller that still holds the original reference
    cannot accidentally persist or log the unredacted version.

    - `str`: registered values and high-signal patterns are replaced.
    - `dict`: any key matching `_KEY_NAME_PATTERN` has its value replaced
      outright (regardless of type); every other value is scrubbed
      recursively.
    - `list` / `tuple`: every element scrubbed recursively, same container
      type preserved.
    - anything else (numbers, bools, `None`, ...): returned unchanged.
    """
    if isinstance(obj, str):
        return _redact_string(obj)
    if isinstance(obj, dict):
        return {
            key: (_KEY_REDACTED_PLACEHOLDER if _KEY_NAME_PATTERN.search(str(key)) else scrub(value))
            for key, value in obj.items()
        }
    if isinstance(obj, tuple):
        return tuple(scrub(item) for item in obj)
    if isinstance(obj, list):
        return [scrub(item) for item in obj]
    return obj


def redaction_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
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
