"""``OpenAIProvider`` — the direct (fallback) lane for OpenAI models (C2 §3).

Reached only when the ADR-033 kill switch is set to ``direct``. Same
OpenAI-compatible wire as the gateway lane, which is why the body builder and
the response translation are shared with ``providers/gateway.py`` rather than
reimplemented: a divergence between the two would be a divergence in what
flipping the kill switch actually does, and that is the one thing the switch
must not have.

Two differences from the gateway lane, both deliberate:

1. **The model id sent is ``provider_model_id``** from
   ``config/models.yaml`` — the vendor has never heard of our alias. The router
   namespace stays lane-invariant because the translation happens here, at the
   edge (C2 §2).
2. **No ``metadata``.** That is a proxy convention for gateway logs; sending
   SUNIL correlation ids to the vendor would be disclosure with no consumer.

The adapter refuses a model the catalogue assigns to another provider before
touching the network: a routing bug must surface as our named error, not as a
vendor 404 three seconds later.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from pydantic import SecretStr

from sunil.core.routing.catalogue import ModelCatalogue
from sunil.providers.base import (
    CompletionRequest,
    CompletionResult,
    ProviderError,
    StreamEvent,
)
from sunil.providers.gateway import DEFAULT_TIMEOUT_S, OpenAICompatibleChat

#: ADR-017's canonical value for the direct lane.
CANONICAL_BASE_URL = "https://api.openai.com"


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: SecretStr,
        base_url: str = CANONICAL_BASE_URL,
        catalogue: ModelCatalogue,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        # ``SecretStr`` is kept as a secret object, never unwrapped onto
        # ``self`` as plaintext (ADR-006): the unwrap happens per call, into a
        # header local.
        self._api_key = api_key
        self._catalogue = catalogue
        self._chat = OpenAICompatibleChat(
            base_url=base_url, catalogue=catalogue, client=client, timeout_s=timeout_s
        )

    async def aclose(self) -> None:
        await self._chat.aclose()

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        wire_model = self._wire_model(request.model)
        body = self._chat.build_body(request, wire_model=wire_model, metadata=False)
        payload = await self._chat.post(
            body, headers=self._headers(), provider_model=wire_model
        )
        return self._chat.result_from(payload, request=request, catalogue_model=request.model)

    def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        wire_model = self._wire_model(request.model)
        body = self._chat.build_body(
            request, wire_model=wire_model, metadata=False, stream=True
        )
        return self._chat.stream_events(
            body,
            headers=self._headers(),
            request=request,
            catalogue_model=request.model,
        )

    # -- internals ---------------------------------------------------------- #
    def _wire_model(self, alias: str) -> str:
        entry = self._catalogue.get_model(alias)
        if entry.provider != self.name:
            raise ProviderError(
                kind="bad_request",
                retryable=False,
                provider_model=None,
                message=(
                    f"model {alias!r} is assigned to provider {entry.provider!r} in "
                    f"config/models.yaml, not to {self.name!r} — refusing before the "
                    "wire (a routing bug, not a vendor error)"
                ),
            )
        return entry.provider_model_id

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
