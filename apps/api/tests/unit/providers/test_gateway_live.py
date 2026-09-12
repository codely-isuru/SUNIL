"""LIVE checks against a running LiteLLM (opt-in, skipped by default).

Enabled only when ``SUNIL_LIVE_GATEWAY_TEST=1`` **and** a key is present in the
environment, so CI and every other stream are unaffected. No secret is written
to a file or asserted on; the key is read from the environment and used once.

Run it (PowerShell, from the repo root) with the generated dev stack up:

    $env:SUNIL_LIVE_GATEWAY_TEST = '1'
    $env:LITELLM_VIRTUAL_KEY_DEFAULT = (Select-String '^LITELLM_MASTER_KEY=' .env).Line.Split('=',2)[1]
    python -m pytest apps/api/tests/unit/providers/test_gateway_live.py -v

What it proves that a mocked transport cannot:

1. the real proxy's ``GET /v1/models`` payload shape is what
   ``GatewayProvider.start()`` parses, and the live alias set really does equal
   ``config/models.yaml`` (C2 §3's parity check, end to end);
2. the pinned LiteLLM refuses an unauthenticated completion with **401**
   (Security review deferred item 7) — observable with no upstream provider key,
   because auth is rejected before any upstream call.
"""

from __future__ import annotations

import os

import pytest
from pydantic import SecretStr

from sunil.core.routing.catalogue import ModelCatalogue
from sunil.providers.base import ProviderError
from sunil.providers.gateway import GatewayProvider, VirtualKeyring
from tests.unit.routing.test_catalogue import repo_root

BASE_URL = os.environ.get("SUNIL_LLM_GATEWAY_BASE_URL", "http://localhost:4000")

live = pytest.mark.skipif(
    os.environ.get("SUNIL_LIVE_GATEWAY_TEST") != "1",
    reason="live gateway check is opt-in: set SUNIL_LIVE_GATEWAY_TEST=1 with the "
    "dev stack up (scripts/dev-up)",
)


def key() -> SecretStr:
    value = os.environ.get("LITELLM_VIRTUAL_KEY_DEFAULT")
    if not value:
        pytest.skip("LITELLM_VIRTUAL_KEY_DEFAULT is not set in this environment")
    return SecretStr(value)


def catalogue() -> ModelCatalogue:
    return ModelCatalogue.load(repo_root() / "config" / "models.yaml")


@live
async def test_live_parity_check_passes_against_the_running_gateway() -> None:
    provider = GatewayProvider(
        base_url=BASE_URL,
        keys=VirtualKeyring(default=key()),
        catalogue=catalogue(),
    )
    try:
        await provider.start()  # raises GatewayModelParityError on drift
    finally:
        await provider.aclose()


def probe_request():
    from sunil.providers.base import ChatMessage, CompletionRequest, PrivacyClass

    return CompletionRequest(
        model="claude-sonnet",
        messages=[ChatMessage(role="user", content="ping")],
        max_tokens=1,
        agent_id="project_manager",
        request_id="live-probe",
        privacy_class=PrivacyClass.INTERNAL,
    )


@live
async def test_live_gateway_rejects_a_completion_with_no_credential_at_all() -> None:
    """Security review deferred item 7, in its literal form: the pinned LiteLLM
    401s a completion call with NO ``Authorization`` header.

    Asserted with a bare ``httpx`` POST rather than through the adapter, because
    the adapter cannot express "no credential": ``VirtualKeyring`` refuses an
    empty key (an empty ``Bearer`` is an illegal header value, see its
    ``__post_init__``). No upstream provider key is needed to observe this —
    auth is rejected before any upstream call, which is exactly why the check is
    runnable in a stack with no vendor credentials.
    """
    import httpx  # noqa: PLC0415

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/v1/chat/completions",
            json={
                "model": "claude-sonnet",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            timeout=20.0,
        )

    assert response.status_code == 401


@live
async def test_live_gateway_rejects_an_unknown_virtual_key_as_auth() -> None:
    """The same rejection as the adapter classifies it: a syntactically valid but
    unregistered key → C2 §4 ``auth``, non-retryable, with the proxy's
    key-echoing body withheld from the message."""
    provider = GatewayProvider(
        base_url=BASE_URL,
        keys=VirtualKeyring(default=SecretStr("sk-not-a-registered-virtual-key")),
        catalogue=catalogue(),
    )
    try:
        with pytest.raises(ProviderError) as err:
            await provider.complete(probe_request())
    finally:
        await provider.aclose()

    assert err.value.kind == "auth"
    assert err.value.retryable is False
    assert "401" in str(err.value)
    # The adapter must not copy the proxy's key-echoing body into the message
    # (see classify_http_error): the live 401 body contains both the presented
    # key and its hash.
    assert "sk-" not in str(err.value)
