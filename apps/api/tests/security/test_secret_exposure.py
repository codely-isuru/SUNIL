"""ET-10 — no secret value in any prompt sent to an LLM, or in any persisted log.

REQUIREMENTS_V1.md ET-10, ADR-006, ARCHITECTURE_V1.md 8.3, THREAT_MODEL
T-21 / T-18 / T-29 / T-30.

Every needle below is an obvious fake. This suite proves the *mechanism*, so
it must never depend on a real value to do it.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import traceback

import pytest
from conftest import FAKE_ENV, REPO_ROOT, SUNIL_PKG, require
from pydantic import SecretStr, ValidationError

# Obvious fakes, deliberately shaped so some match ADR-006 high-signal
# patterns and some do not — a control that only catches sk-ant-... is not a
# control.
NEEDLE_PATTERNED = "sk-ant-fake000000000000000000000000"
NEEDLE_UNPATTERNED = "fake-session-secret-no-regex-will-ever-match-this"
NEEDLE_DB_PASSWORD = "fake-db-password-no-pattern"
FAKE_PG_URL = f"postgresql+psycopg://sunil:{NEEDLE_DB_PASSWORD}@db:5432/sunil"

SECRET_NAME_PATTERN = re.compile(r"(api_key|apikey|token|secret|password|credential)", re.I)


# ---------------------------------------------------------------------------
# Part 1 — the type-level control. Green today; locked so a refactor cannot
# quietly remove it.
# ---------------------------------------------------------------------------


def test_every_secret_named_field_is_a_secretstr(fake_env: dict[str, str]) -> None:
    """ADR-006: every secret typed SecretStr, never str. Derive the list from
    the field names rather than restating it, so it cannot drift."""
    from sunil.settings import Settings

    offenders = [
        name
        for name, field in Settings.model_fields.items()
        if SECRET_NAME_PATTERN.search(name) and field.annotation is not SecretStr
    ]
    assert not offenders, f"secret-named fields typed as plain str: {offenders}"


def test_no_secretstr_renders_its_value_in_any_common_rendering(
    fake_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ADR-006 [REDACTED] claim through every rendering a developer or a
    library might reach for — including database_url, the one secret that
    carries an embedded credential."""
    monkeypatch.setenv("DATABASE_URL", FAKE_PG_URL)
    from sunil.settings import Settings

    settings = Settings(_env_file=None)
    # Only the SecretStr-typed fields. OWNER_USERNAME is a non-secret str
    # (ARCHITECTURE_V1.md 14.4 marks it "Secret: no") and legitimately appears
    # in repr(settings) — asserting otherwise would be a false positive.
    needles = [
        value
        for name, value in FAKE_ENV.items()
        if Settings.model_fields[name.lower()].annotation is SecretStr
    ] + [NEEDLE_DB_PASSWORD]
    renderings = {
        "repr(settings)": repr(settings),
        "str(settings)": str(settings),
        "model_dump_json()": settings.model_dump_json(),
        "model_dump()": str(settings.model_dump()),
        "model_dump(mode=json)": str(settings.model_dump(mode="json")),
        "f-string of a field": f"{settings.anthropic_api_key} {settings.database_url}",
    }
    leaks = {
        name: needle for name, text in renderings.items() for needle in needles if needle in text
    }
    assert not leaks, f"a secret value rendered in plain text: {leaks}"


def test_settings_failure_never_exposes_an_already_loaded_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure path, which is the one that leaks.

    pydantic reports a *missing* field with `input` set to the whole collected
    settings dict. At that moment every other secret is still a raw str —
    SecretStr coercion happens after validation — so the exception carries
    them verbatim.

    This is also the one path T4 redaction cannot rescue: ADR-006 registers
    values for successfully *loaded* secrets, and on this path none loaded.
    """
    for key, value in FAKE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("ANTHROPIC_API_KEY", NEEDLE_PATTERNED)
    monkeypatch.setenv("SESSION_SECRET", NEEDLE_UNPATTERNED)
    monkeypatch.setenv("DATABASE_URL", FAKE_PG_URL)
    monkeypatch.delenv("OWNER_PASSWORD", raising=False)

    from sunil.settings import Settings

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)

    exc = excinfo.value
    renderings = {
        "str(exc)": str(exc),
        "repr(exc)": repr(exc),
        "exc.json()": exc.json(),
        "exc.errors()": json.dumps(exc.errors(), default=str),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }
    needles = {
        "ANTHROPIC_API_KEY": NEEDLE_PATTERNED,
        "SESSION_SECRET": NEEDLE_UNPATTERNED,
        "DATABASE_URL password": NEEDLE_DB_PASSWORD,
    }
    leaks = [
        f"{rendering} leaks {name}"
        for rendering, text in renderings.items()
        for name, needle in needles.items()
        if needle in text
    ]
    assert not leaks, (
        "a failed Settings() construction exposed already-loaded secrets (ET-10):\n  "
        + "\n  ".join(leaks)
    )


def test_a_failed_settings_load_never_writes_a_secret_to_a_log_line(
    monkeypatch: pytest.MonkeyPatch, log_capture
) -> None:
    """The same defect end to end through the real T1 structlog chain, because
    "any persisted log" is ET-10 actual wording and format_exc_info renders
    str(exc) straight into the JSON line."""
    for key, value in FAKE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("ANTHROPIC_API_KEY", NEEDLE_PATTERNED)
    monkeypatch.delenv("OWNER_PASSWORD", raising=False)

    from sunil.logging import get_logger
    from sunil.settings import Settings

    log = get_logger("startup")
    try:
        Settings(_env_file=None)
    except ValidationError as exc:
        log.exception("settings_failed_to_load")
        log.error("settings_validation_errors", errors=exc.errors())

    output = log_capture.getvalue()
    assert NEEDLE_PATTERNED not in output, (
        "a secret value reached a rendered log line (ET-10). Output:\n" + output[:2000]
    )


# ---------------------------------------------------------------------------
# Part 2 — the redaction mechanism. RED until T4.
# ---------------------------------------------------------------------------


def test_registered_secret_never_appears_in_log_output(log_capture) -> None:
    """ET-10 test 1 (THREAT_MODEL section 11, ADR-006)."""
    redaction = require("sunil.redaction", "T4 (trace / audit / redaction)")

    redaction.register(NEEDLE_UNPATTERNED)
    from sunil.logging import get_logger

    get_logger("t").info(
        "tool_result", detail={"nested": [{"value": f"prefix {NEEDLE_UNPATTERNED} suffix"}]}
    )
    output = log_capture.getvalue()
    assert NEEDLE_UNPATTERNED not in output, f"registered secret survived scrubbing: {output}"


def test_redaction_processor_is_registered_in_both_structlog_chains() -> None:
    """sunil/logging.py tells T4 to register redaction by appending to the
    module-level shared_processors list. That list is passed *by reference* to
    ProcessorFormatter(foreign_pre_chain=...) but *unpacked into a copy* for
    structlog.configure(processors=[*shared_processors, ...]).

    So an append after configure_logging() has run redacts uvicorn lines and
    silently does not redact structlog lines. This asserts the redactor is in
    both chains, whatever registration order T4 picks.
    """
    import logging as stdlib_logging

    import structlog

    redaction = require("sunil.redaction", "T4 (trace / audit / redaction)")
    from sunil.logging import configure_logging

    configure_logging()

    def names(processors) -> set[str]:
        return {getattr(p, "__name__", type(p).__name__) for p in processors or ()}

    expected = {getattr(redaction.scrub_processor, "__name__", "scrub_processor")}
    structlog_chain = names(structlog.get_config()["processors"])
    formatter = stdlib_logging.getLogger().handlers[0].formatter
    foreign_chain = names(getattr(formatter, "foreign_pre_chain", ()))

    assert expected & structlog_chain, (
        f"no redaction processor in the structlog chain: {sorted(structlog_chain)}"
    )
    assert expected & foreign_chain, (
        f"no redaction processor in the foreign (uvicorn) chain: {sorted(foreign_chain)}"
    )


def test_registered_secret_never_appears_in_a_persisted_llm_call() -> None:
    """ET-10 test 2 — the persistence half (ADR-006: scrub() runs on
    llm_calls.request_* / response_* before insert)."""
    require("sunil.redaction", "T4")
    require("sunil.db.models", "T2 (data layer)")
    capture = require("sunil.db.capture", "T2 (data layer)")

    row = capture.build_llm_call_row(
        request_messages=[
            {"role": "user", "content": f"please use key {NEEDLE_PATTERNED} to continue"}
        ],
        response_text="ok",
    )
    serialised = json.dumps(row, default=str)
    assert NEEDLE_PATTERNED not in serialised, f"secret persisted into llm_calls: {serialised}"


def test_a_sqlalchemy_url_object_never_reaches_a_log_line(log_capture) -> None:
    """sqlalchemy.engine.URL is a NamedTuple. URL.__repr__ / __str__ mask the
    password, but the structlog JSONRenderer serialises a tuple natively as a
    JSON array, so the masking never runs and the password is emitted in
    clear. database_url: SecretStr protects the *setting*; it does not protect
    the object T2 derives from it."""
    require("sunil.db.session", "T2 (data layer)")
    from sqlalchemy.engine import make_url
    from sunil.logging import get_logger

    get_logger("db").info("engine_ready", url=make_url(FAKE_PG_URL))
    output = log_capture.getvalue()
    assert NEEDLE_DB_PASSWORD not in output, (
        "a SQLAlchemy URL leaked its password through the JSON renderer:\n" + output
    )


# ---------------------------------------------------------------------------
# Part 3 — the static half: nothing on disk or in git carries a value.
# Green today.
# ---------------------------------------------------------------------------

CREDENTIAL_PATTERNS = (
    re.compile(r"sk-ant-(?!fake|REPLACE)[A-Za-z0-9_-]{16,}"),
    re.compile(r"gh[pousr]_(?!fake|REPLACE)[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_(?!fake|REPLACE)[A-Za-z0-9_]{30,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
PLACEHOLDER = re.compile(
    r"^(|REPLACE_ME.*|.*REPLACE_ME|sqlite\+aiosqlite:.*|https?://localhost:\d+|"
    r"127\.0\.0\.1|INFO|false|true|\d+|\./config|sunil_session|isuru|"
    # A-11/ADR-017: the canonical upstream base URLs are not secrets — they
    # are the public, well-known API hosts, and showing the real default
    # (rather than a placeholder) is normal `.env.example` practice for a
    # non-secret operational default, exactly like WEB_ORIGIN above.
    r"https://api\.anthropic\.com|https://api\.github\.com)$"
)


def test_env_example_carries_placeholders_only() -> None:
    """T1 own Watch note: a real value in .env.example is an ET-10 failure.
    The repository is public, so that is publication, not merely exposure."""
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    offenders = [
        f"{m.group(1)}={m.group(2)}"
        for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=(.*)$", text, re.M)
        if not PLACEHOLDER.match(m.group(2).strip())
    ]
    assert not offenders, f".env.example carries non-placeholder values: {offenders}"


def test_env_example_matches_the_settings_inventory(fake_env: dict[str, str]) -> None:
    """sunil/settings.py line 101 claims "CI can validate .env.example against
    it". No CI step did. This is that validation."""
    from sunil.settings import Settings

    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    documented = {m.group(1) for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=", text, re.M)}
    declared = {name.upper() for name in Settings.model_fields}
    assert documented == declared, (
        f"missing from .env.example: {sorted(declared - documented)}; "
        f"undeclared in Settings: {sorted(documented - declared)}"
    )


def test_no_tracked_file_contains_a_credential() -> None:
    """T-29 / TB7 — where a secret leaks permanently.

    Scans every tracked file at HEAD. Note for T21: actions/checkout clones at
    depth 1, so extending this to full history needs fetch-depth: 0.
    """
    # noqa placement: ruff reports S607 on the argument list, not the call.
    listed = subprocess.run(  # noqa: S603
        ["git", "ls-files", "-z"],  # noqa: S607 - resolving `git` from PATH is the intent
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    offenders: list[str] = []
    for name in filter(None, listed.stdout.split("\0")):
        path = REPO_ROOT / name
        if path.name == "test_secret_exposure.py":
            continue
        if not path.is_file() or path.suffix in {".png", ".ico", ".woff2", ".jpg", ".lock"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in CREDENTIAL_PATTERNS:
            for match in pattern.finditer(content):
                line = content[: match.start()].count("\n") + 1
                offenders.append(f"{name}:{line} {match.group(0)[:24]}...")
    assert not offenders, "credential-shaped strings in tracked files:\n  " + "\n  ".join(offenders)


def test_dev_check_reports_presence_only_for_every_secretstr_field(
    fake_env: dict[str, str],
) -> None:
    """scripts/dev-check.ps1 promises "presence only, NEVER the value" for
    every SecretStr variable, but keeps a hand-written $secretKeys list. Add a
    SecretStr field to settings.py and to $requiredKeys, forget $secretKeys,
    and the script prints its value. This is the mechanism behind the promise."""
    from sunil.settings import Settings

    script = (REPO_ROOT / "scripts" / "dev-check.ps1").read_text(encoding="utf-8")
    match = re.search(r"\$secretKeys\s*=\s*@\((.*?)\)", script, re.S)
    assert match, "could not find $secretKeys in scripts/dev-check.ps1"
    declared = {
        item.strip().strip('"').strip("'")
        for item in match.group(1).replace("\n", " ").split(",")
        if item.strip()
    }
    expected = {
        name.upper()
        for name, field in Settings.model_fields.items()
        if field.annotation is SecretStr
    }
    assert declared == expected, (
        f"dev-check.ps1 would print the value of: {sorted(expected - declared)}; "
        f"lists non-secrets as secret: {sorted(declared - expected)}"
    )


def test_no_module_logs_a_settings_object_wholesale() -> None:
    """Defence in depth behind SecretStr: repr(Settings) is safe today, but
    passing the object into a log field makes every future field a one-typo
    leak. Keep configuration out of log payloads entirely."""
    offenders: list[str] = []
    for path in sorted(SUNIL_PKG.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {
                "debug",
                "info",
                "warning",
                "error",
                "exception",
                "critical",
            }:
                continue
            for keyword in node.keywords:
                if isinstance(keyword.value, ast.Name) and keyword.value.id in {
                    "settings",
                    "config",
                }:
                    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
                    offenders.append(f"{rel}:{node.lineno} logs `{keyword.value.id}` wholesale")
    assert not offenders, "\n  ".join(offenders)
