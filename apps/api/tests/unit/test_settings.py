"""``sunil.settings`` — the single env seam (ARCHITECTURE_V2 §5).

Every assertion below is a row of §5's config inventory or one of the two
validators the inventory names (ADR-033's named-host rule, ADR-017's canonical
base URLs). The inventory is the contract: a default that drifts from it is a
defect, because `.env.example`, the Compose ports and the L-001 trace are all
written against these values.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from sunil.settings import Settings

# Fields §5 marks "— required". Passed explicitly by every test so that no
# assertion depends on an ambient environment variable or a repo-root `.env`.
REQUIRED = {"session_secret": "unit-test-session-secret"}


@pytest.fixture(autouse=True)
def _no_ambient_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings reads the process environment by design; a test asserting a
    DEFAULT must not be answered by the developer's shell."""
    for name in (
        "DATABASE_URL",
        "SESSION_SECRET",
        "SESSION_COOKIE_NAME",
        "WEB_ORIGIN",
        "API_HOST",
        "API_PORT",
        "LOG_LEVEL",
        "SUNIL_CONFIG_DIR",
        "SUNIL_TURN_DEADLINE_S",
        "SUNIL_LLM_PROVIDER_LANE",
        "SUNIL_LLM_GATEWAY_BASE_URL",
        "SUNIL_N8N_MCP_BASE_URL",
        "SUNIL_OPENHANDS_BASE_URL",
        "SUNIL_APPROVAL_TTL_HOURS",
        "SUNIL_APPROVAL_CONSUME_GRACE_HOURS",
        "SUNIL_APPROVAL_NOTIFY_WEBHOOK_URL",
        "SUNIL_SERVICE_TOKEN",
        "SUNIL_MEMORY_PROVIDER",
        "SUNIL_TOOL_MANAGER",
        "SUNIL_APPROVALS_SERVICE",
    ):
        monkeypatch.delenv(name, raising=False)


def build(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**REQUIRED, **overrides})  # type: ignore[arg-type]


def test_defaults_are_the_architecture_v2_section_5_inventory() -> None:
    settings = build()

    assert settings.database_url.get_secret_value() == (
        "postgresql+psycopg://sunil:CHANGE_ME@localhost:5433/sunil"
    )
    assert settings.session_cookie_name == "sunil_session"
    assert settings.web_origin == "http://localhost:3001"  # ADR-032 Amendment 1
    assert (settings.api_host, settings.api_port) == ("127.0.0.1", 8000)
    assert settings.log_level == "INFO"
    assert settings.sunil_config_dir == "./config"
    assert settings.sunil_turn_deadline_s == 40
    assert settings.sunil_llm_provider_lane == "gateway"
    assert settings.sunil_llm_gateway_base_url == "http://localhost:4000"
    # The workflow path, not the bare `/mcp` prefix (ADR-033 Amendment 1 item 2,
    # from S2-E §7 item 1: `/mcp` is a prefix and answers 404 on the live n8n).
    assert settings.sunil_n8n_mcp_base_url == "http://localhost:5680/mcp/sunil"
    # ADR-033 Amendment 1 item 1. The ADR-032 port pair the commented Compose
    # block already carries (127.0.0.1:3400 -> 3000).
    assert settings.sunil_openhands_base_url == "http://localhost:3400"
    assert settings.sunil_approval_ttl_hours == 72
    assert settings.sunil_approval_consume_grace_hours == 1
    assert settings.sunil_approval_notify_webhook_url is None  # webhook off
    assert settings.sunil_memory_provider == "fake"  # until Stream C lands


def test_the_machine_lane_is_off_when_the_token_is_absent() -> None:
    """§5: `SUNIL_SERVICE_TOKEN` `unset (machine lane off)` is the fail-closed
    application default — dev-up generating one does not change that."""
    assert build().sunil_service_token is None


def test_secrets_are_secretstr_and_never_render_their_value() -> None:
    settings = build(session_secret="hunter2-the-literal-value", sunil_service_token="tok-abc123")

    assert isinstance(settings.session_secret, SecretStr)
    assert isinstance(settings.sunil_service_token, SecretStr)
    for rendered in (repr(settings), str(settings), repr(settings.session_secret)):
        assert "hunter2-the-literal-value" not in rendered
        assert "tok-abc123" not in rendered


# --------------------------------------------------------------------------- #
# ADR-033 — the named-host egress rule. C2 contract test 6 asserts the first
# case through the frozen contract suite; these cover the whole rule.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:4000",
        "http://127.0.0.1:4000",
        "http://litellm:4000",  # the literal Compose service host
    ],
)
def test_gateway_base_url_accepts_loopback_and_the_compose_host(url: str) -> None:
    assert build(sunil_llm_gateway_base_url=url).sunil_llm_gateway_base_url == url


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example",
        "http://litellm.evil.example:4000",  # substring of the named host, not the host
        "http://10.0.0.5:4000",
    ],
)
def test_gateway_base_url_refuses_anything_else(url: str) -> None:
    with pytest.raises(ValueError, match="sunil_llm_gateway_base_url"):
        build(sunil_llm_gateway_base_url=url)


@pytest.mark.parametrize(
    "url", ["http://localhost:5680/mcp", "http://n8n:5678/mcp", "http://127.0.0.1:5680/mcp"]
)
def test_n8n_mcp_base_url_accepts_loopback_and_the_compose_host(url: str) -> None:
    assert build(sunil_n8n_mcp_base_url=url).sunil_n8n_mcp_base_url == url


def test_n8n_mcp_base_url_refuses_a_public_host() -> None:
    with pytest.raises(ValueError, match="sunil_n8n_mcp_base_url"):
        build(sunil_n8n_mcp_base_url="https://n8n.example.com/mcp")


@pytest.mark.parametrize(
    "url", ["http://localhost:3400", "http://127.0.0.1:3400", "http://openhands:3000"]
)
def test_openhands_base_url_accepts_loopback_and_the_compose_host(url: str) -> None:
    """ADR-033 Amendment 1: `openhands` joins the named-host set for THIS field.

    The field may be read by nothing yet — the Compose service is still
    commented out pending the runtime-isolation ADR (S2-F §4) — and that is
    fine: an unread validated setting is inert, and the alternative is landing
    the guard in the same change that first sends bytes anywhere.
    """
    assert build(sunil_openhands_base_url=url).sunil_openhands_base_url == url


@pytest.mark.parametrize(
    "url",
    [
        "https://app.all-hands.dev",  # the vendor's hosted runtime
        "http://openhands.evil.example:3000",  # substring of the named host
        "http://192.168.1.40:3400",
    ],
)
def test_openhands_base_url_refuses_anything_else(url: str) -> None:
    """The engine receives a work order and returns a report SUNIL acts on. A
    redirectable base URL would let anything that can influence process env
    choose who writes that report."""
    with pytest.raises(ValueError, match="sunil_openhands_base_url"):
        build(sunil_openhands_base_url=url)


def test_the_named_host_set_is_closed_literal_and_scoped_per_field() -> None:
    """ADR-033: "a frozen constant in code, not configuration". Asserted WHOLE,
    so a host added to it comes past this test — and asserted per field, because
    the set is not one bag: `litellm` is not admissible for the n8n MCP URL and
    `openhands` is not admissible for anything but its own field.
    """
    from sunil.settings import _NAMED_HOSTS

    assert _NAMED_HOSTS == {
        "sunil_llm_gateway_base_url": ("litellm",),
        "sunil_n8n_mcp_base_url": ("n8n",),
        "sunil_approval_notify_webhook_url": ("n8n",),
        "sunil_openhands_base_url": ("openhands",),
    }


@pytest.mark.parametrize(
    ("field", "url"),
    [
        ("sunil_llm_gateway_base_url", "http://openhands:3000"),
        ("sunil_n8n_mcp_base_url", "http://openhands:3000/mcp/sunil"),
        ("sunil_approval_notify_webhook_url", "http://openhands:3000/hook"),
    ],
)
def test_the_new_named_host_widens_no_other_field(field: str, url: str) -> None:
    """The failure mode a single shared set would have: adding `openhands` for
    the developer seam must not make an approval notification — a redacted
    summary of what an owner is being asked to authorise — postable to it."""
    with pytest.raises(ValueError, match=field):
        build(**{field: url})


def test_notify_webhook_url_is_validated_when_set_and_optional_when_not() -> None:
    """TB8: the webhook is off by default, and a configured one is still bound by
    ADR-033 — a redacted approval summary must not be postable to any host."""
    assert build(sunil_approval_notify_webhook_url="http://n8n:5678/webhook/x")
    with pytest.raises(ValueError, match="sunil_approval_notify_webhook_url"):
        build(sunil_approval_notify_webhook_url="https://exfil.example/hook")


def test_session_secret_is_required_and_has_no_default() -> None:
    """A defaulted signing key is a forged-cookie hole that ships silently."""
    with pytest.raises(ValueError, match="session_secret"):
        Settings(_env_file=None)


def test_web_origin_must_be_localhost_not_127_0_0_1() -> None:
    """ADR-008: the browser-facing name is `localhost`, so the session cookie is
    same-site with the page. `127.0.0.1` is a different site to a browser."""
    with pytest.raises(ValueError, match="web_origin"):
        build(web_origin="http://127.0.0.1:3001")


def test_a_failed_load_never_echoes_a_loaded_value() -> None:
    """M1's ET-10 lesson: pydantic reports a MISSING-field error's `input` as the
    whole collected values dict, and `SecretStr` coercion happens only after
    validation — so every secret that DID load is a raw `str` in that payload."""
    with pytest.raises(ValueError) as err:
        Settings(_env_file=None, sunil_service_token="super-secret-token-value")

    rendered = str(err.value) + repr(err.value.errors())
    assert "super-secret-token-value" not in rendered
