"""ET-10 — no secret value in any prompt sent to an LLM, or in any persisted log.

REQUIREMENTS_V1.md ET-10, ADR-006, ARCHITECTURE_V1.md 8.3, THREAT_MODEL
T-21 / T-18 / T-29 / T-30.

Every needle below is an obvious fake. This suite proves the *mechanism*, so
it must never depend on a real value to do it.
"""

from __future__ import annotations

import ast
import inspect
import json
import pathlib
import re
import subprocess
import traceback

import pytest
from pydantic import SecretStr, ValidationError
from security_helpers import FAKE_ENV, REPO_ROOT, SUNIL_PKG, require

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
        "f-string of a field": (
            f"{settings.anthropic_api_key} {settings.openai_api_key} {settings.database_url}"
        ),
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


def test_every_capture_table_writer_scrubs_its_content_columns() -> None:
    """ET-10's persistence half, mechanised.

    This file previously called a central `build_llm_call_row()`. That was the
    wrong assumption, and the right answer is now explicit in
    `sunil/redaction.py`'s own docstring: "**T6 and T8 must call scrub()
    themselves** ... this module provides the mechanism; it does not, and
    structurally cannot, reach into another lane's insert call site."

    That is a defensible design, but as written it makes ET-10's persistence
    guarantee a convention repeated across N lanes — the exact shape ADR-006
    says it rejects ("a control with no mechanism behind it is a claim"). So
    the mechanism is here instead: any module that constructs a row for one of
    the five capture tables must pass its content columns through `scrub()`.

    T8's `manager.py` does this correctly today (`parameters=scrub(params)`),
    which is what makes this test green rather than theoretical — it is a
    regression lock on a convention, not a wish.
    """
    require("sunil.redaction", "T4")
    models = require("sunil.db.models", "T2")

    content_columns = {
        "Message": {"content"},
        "Plan": {"plan_json", "validation_errors"},
        "LLMCall": {"request_messages", "response_text", "response_json"},
        "ToolCall": {"parameters", "result"},
        "Memory": {"content"},
    }
    known = {
        name: {c.name for c in getattr(models, name).__table__.columns} for name in content_columns
    }
    unscrubbed: list[str] = []

    for path in sorted(SUNIL_PKG.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        # Names bound to an expression that already went through scrub(), so a
        # module that scrubs into a local and passes the local is not flagged.
        # (T8 does exactly this: `stored_result = ... scrub(result) ...`.)
        scrubbed_locals = {
            target.id
            for assign in ast.walk(tree)
            if isinstance(assign, ast.Assign) and "scrub(" in ast.unparse(assign.value)
            for target in assign.targets
            if isinstance(target, ast.Name)
        }
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            model_name = node.func.id
            if model_name not in content_columns:
                continue
            for keyword in node.keywords:
                if keyword.arg is None or keyword.arg not in known[model_name]:
                    continue
                if keyword.arg not in content_columns[model_name]:
                    continue
                if isinstance(keyword.value, ast.Constant) and keyword.value.value is None:
                    continue  # explicit NULL is already safe
                source = ast.unparse(keyword.value)
                if "scrub(" not in source and source not in scrubbed_locals:
                    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
                    unscrubbed.append(
                        f"{rel}:{node.lineno} {model_name}(...{keyword.arg}={source[:60]}) "
                        "is written without scrub()"
                    )
    assert not unscrubbed, (
        "a capture-table content column is persisted without ADR-006 redaction:"
        + "\n  "
        + ("\n  ").join(unscrubbed)
    )


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

# Two tiers, deliberately. Production code must contain nothing that even
# *looks* like a credential. Test files legitimately contain credential-shaped
# fixtures, so they are matched against the real issued shapes only — an
# Anthropic key is `sk-ant-api03-` + ~95 chars, a fine-grained PAT is
# `github_pat_` + 22 + `_` + 59. Excluding tests/ wholesale would be the wrong
# fix: pasting a real key into a test while debugging is a realistic leak path,
# and that is exactly what the strict tier still catches.
_BROAD_PATTERNS = (
    re.compile(r"sk-ant-(?!fake|REPLACE)[A-Za-z0-9_-]{16,}"),
    re.compile(r"gh[pousr]_(?!fake|REPLACE)[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_(?!fake|REPLACE)[A-Za-z0-9_]{30,}"),
)
_REAL_SHAPE_PATTERNS = (
    re.compile(r"sk-ant-api\d{2}-[A-Za-z0-9_-]{60,}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"github_pat_[A-Za-z0-9]{22}_[A-Za-z0-9]{59}"),
)
_ALWAYS_PATTERNS = (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),)

# Non-secret values that are legitimately real in `.env.example`: the SQLite
# default and the three canonical upstream API hosts (ADR-017 — an override must
# be the canonical host or loopback, so the canonical value IS the placeholder).
PLACEHOLDER = re.compile(
    r"^(|REPLACE_ME.*|.*REPLACE_ME|sqlite\+aiosqlite:.*|https?://localhost:\d+|"
    r"https://api\.github\.com|https://api\.anthropic\.com|https://api\.openai\.com/v1|"
    r"127\.0\.0\.1|INFO|false|true|\d+|\./config|sunil_session|isuru)$"
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
        is_test = "/tests/" in name.replace("\\", "/") or name.startswith("tests/")
        patterns = _ALWAYS_PATTERNS + (_REAL_SHAPE_PATTERNS if is_test else _BROAD_PATTERNS)
        for pattern in patterns:
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


# ---------------------------------------------------------------------------
# Part 4 — egress. ADR-017 section 3: the guard that makes the base-URL test
# seam safe. This is credential *theft*, not disclosure, so it gets its own
# section rather than sitting among the redaction tests.
# ---------------------------------------------------------------------------

CANONICAL_BASE_URLS = {
    "anthropic_base_url": "https://api.anthropic.com",
    "github_api_base_url": "https://api.github.com",
    "openai_base_url": "https://api.openai.com/v1",
}
HOSTILE_BASE_URLS = (
    "https://attacker.example.com",
    "http://169.254.169.254",  # cloud instance metadata
    "https://api.github.com.evil.test",  # canonical host as a prefix
    "https://localhost.evil.test",  # canonical loopback name as a prefix
    "http://127.0.0.1.evil.test",
)
LOOPBACK_BASE_URLS = ("http://localhost:8099", "http://127.0.0.1:8099", "http://[::1]:8099")


def test_a_hostile_api_base_url_refuses_to_construct_settings(
    fake_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-017 section 3, verbatim: "Value equals the canonical host -> allowed.
    Host is localhost, 127.0.0.0/8 or ::1 -> allowed. Anything else ->
    ValidationError at construction, so the application refuses to boot. **This
    is not optional hardening.**"

    ADR-017 states the threat itself: "redirect the GitHub URL and the request
    carries `Authorization: Bearer <PAT>` to the attacker's host — credential
    theft, not just disclosure. And nothing in the audit trail would look wrong,
    because from SUNIL's side the call succeeded."

    The GitHub adapter puts the PAT in an `Authorization` header on every one of
    its three requests and prefixes `settings.github_api_base_url` onto the
    path, so an unguarded field is a one-environment-variable exfiltration
    primitive for a read token on a private business repository.
    """
    from sunil.settings import Settings

    for field_name in CANONICAL_BASE_URLS:
        if field_name not in Settings.model_fields:
            pytest.fail(
                f"RED — control absent, test intact: `Settings.{field_name}` does not exist on "
                "this branch (owed by T6 for anthropic_base_url / T8 for github_api_base_url). "
                "ADR-017 section 2 requires both."
            )

    unguarded: list[str] = []
    for field_name, env_var in (
        ("anthropic_base_url", "ANTHROPIC_BASE_URL"),
        ("github_api_base_url", "GITHUB_API_BASE_URL"),
        ("openai_base_url", "OPENAI_BASE_URL"),
    ):
        for hostile in HOSTILE_BASE_URLS:
            monkeypatch.setenv(env_var, hostile)
            try:
                Settings(_env_file=None)
            except ValidationError:
                continue
            unguarded.append(f"{field_name}={hostile} was accepted")
        monkeypatch.delenv(env_var, raising=False)

    assert not unguarded, (
        "ADR-017 section 3's loopback guard is missing — these are accepted where the ADR "
        "requires the application to refuse to boot:" + "\n  " + ("\n  ").join(unguarded)
    )


def test_the_canonical_and_loopback_base_urls_are_still_accepted(
    fake_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of ADR-017 section 3: the guard must not break the test
    seam it exists to protect. A guard that rejected loopback would push QA
    back to hitting the real API with a real key — the failure ADR-017 was
    written to prevent."""
    from sunil.settings import Settings

    for field_name, env_var in (
        ("anthropic_base_url", "ANTHROPIC_BASE_URL"),
        ("github_api_base_url", "GITHUB_API_BASE_URL"),
        ("openai_base_url", "OPENAI_BASE_URL"),
    ):
        if field_name not in Settings.model_fields:
            pytest.fail(
                f"RED — control absent, test intact: `Settings.{field_name}` does not exist "
                "(owed by T6 / T8 / T23, ADR-017 section 2)."
            )
        for allowed in (CANONICAL_BASE_URLS[field_name], *LOOPBACK_BASE_URLS):
            monkeypatch.setenv(env_var, allowed)
            Settings(_env_file=None)  # must not raise
        monkeypatch.delenv(env_var, raising=False)


def test_the_github_client_never_follows_a_redirect() -> None:
    """ADR-017 consequences: "`follow_redirects` stays `False` on the GitHub
    client, so a local double cannot bounce the PAT onward with a 302."

    httpx defaults to `False`, so this is currently satisfied by accident
    rather than by statement — and a later engineer adding
    `follow_redirects=True` to chase a GitHub 301 would silently re-open the
    exfiltration path the loopback guard closes.
    """
    adapter_mod = require("sunil.tools.github.adapter", "T8")

    source = pathlib.Path(inspect.getfile(adapter_mod)).read_text(encoding="utf-8")
    assert "follow_redirects=False" in source, (
        "the GitHub client does not state `follow_redirects=False`. httpx's default happens to be "
        "False, so the PAT is safe today by coincidence rather than by decision (ADR-017)."
    )
