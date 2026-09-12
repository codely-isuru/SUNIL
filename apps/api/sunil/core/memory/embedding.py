"""Embeddings behind a seam of their own — C3 §2's last normative bullet.

> **Embeddings** are obtained through the C2 gateway, so embedding calls inherit
> routing, budgets and audit like every other model call.

Two implementations satisfy `Embedder`:

* `HashingEmbedder` — deterministic, local, no key, no network. The test suite
  runs on it, and so does any deployment that has no embedding credential yet:
  memory still works, retrieval is lexical-by-hashing rather than semantic.
* `GatewayEmbedder` — the production one. POSTs to the LiteLLM gateway's
  OpenAI-compatible `/v1/embeddings`, so routing, per-key budgets and the
  gateway's own spend log apply.

**What is NOT claimed.** `GatewayEmbedder` does not flow through C2's
`LLMProvider.complete` — the frozen C2 interface has no `embed` method, and
adding one is a MAJOR contract change owned by Stream B, not something a memory
provider may do on its way past. So embedding calls inherit the gateway's
routing and budgets, and are logged by LiteLLM, but they do NOT appear in
SUNIL's own `llm_calls` rows. That is a real gap against the bullet's word
"audit", recorded here rather than papered over; closing it is a C2 change.

**The dimension is schema, not configuration.** `memories.embedding` is
`vector(EMBEDDING_DIM)`. An embedder of another width is a migration, not a
config flip, so both implementations declare `dimension` and the provider
refuses to be built around a mismatch — the failure lands at construction with
both numbers in the message, not at the first INSERT with a driver error.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Protocol

import httpx

#: The width of `memories.embedding`. 1536 = OpenAI `text-embedding-3-small`,
#: the default production model; the local embedder hashes into the same width
#: so the schema has exactly one answer.
EMBEDDING_DIM = 1536

#: Words, for the local embedder. Splitting on non-alphanumerics makes
#: `"Winch, Recovery."` and `"winch recovery"` the same bag.
_TOKEN = re.compile(r"[a-z0-9]+")


class EmbeddingUnavailableError(Exception):
    """The embedding call failed, or returned something unusable.

    ONE type, deliberately: the provider translates this into C3 §4's
    `MemoryUnavailableError` so the turn degrades. It could not do that if httpx's
    exception hierarchy leaked through the seam.
    """


class Embedder(Protocol):
    name: str
    dimension: int

    async def embed(self, text: str) -> list[float]: ...


def _normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


class HashingEmbedder:
    """Bag-of-words hashed into `dimension` buckets, L2-normalised.

    `hashlib.blake2b`, never the builtin `hash()`: `PYTHONHASHSEED` randomises
    `hash()` per process, so a builtin-hashed embedder would write vectors in
    one process that a later process could not match — silently, and only ever
    in production, where the writer and the reader are different runs.

    Retrieval quality: cosine similarity here is monotone in token overlap, so
    "more of the query's words appear" ranks higher. That is lexical, not
    semantic — no synonym, no paraphrase. Honest for a test double and for a
    keyless deployment; not a substitute for a real embedding model.
    """

    def __init__(self, dimension: int = EMBEDDING_DIM) -> None:
        self.name = "hashing"
        self.dimension = dimension

    def _bucket(self, token: str) -> int:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, "big") % self.dimension

    async def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in _TOKEN.findall(text.lower()):
            vector[self._bucket(token)] += 1.0
        return _normalise(vector)


class GatewayEmbedder:
    """OpenAI-compatible `/v1/embeddings` on the C2 gateway.

    The base URL is validated by `Settings` under ADR-033's named-host rule
    before it ever reaches here — an outbound base is an exfiltration channel,
    and this class must not become a second, unvalidated way to name one.

    **Live-unproven.** No embedding credential exists on the build machine, so
    every test against this class uses a mock transport: request shape, width
    check and failure translation are proven; an actual LiteLLM round-trip is
    not.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        dimension: int = EMBEDDING_DIM,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        self.name = f"gateway:{model}"
        self.dimension = dimension
        self._url = base_url.rstrip("/") + "/v1/embeddings"
        self._model = model
        self._api_key = api_key
        self._timeout_s = timeout_s
        self._client = client
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_s)
        return self._client

    async def embed(self, text: str) -> list[float]:
        try:
            response = await self._http().post(
                self._url,
                json={"model": self._model, "input": text},
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.HTTPError as exc:  # transport-level
            raise EmbeddingUnavailableError(
                f"embedding request to the gateway failed: {type(exc).__name__}"
            ) from exc

        if response.status_code != 200:
            # The body may echo an upstream provider message; the status alone is
            # what this layer needs, and a body could carry a key fragment.
            raise EmbeddingUnavailableError(
                f"gateway returned HTTP {response.status_code} for an embedding call"
            )

        vector = _extract_vector(response.json())
        if len(vector) != self.dimension:
            raise EmbeddingUnavailableError(
                f"embedding model {self._model!r} returned width {len(vector)}, but "
                f"the memories.embedding column is vector({self.dimension}). "
                "Changing embedding family is a migration, not a config flip."
            )
        return vector


def _extract_vector(payload: Any) -> list[float]:
    try:
        data = payload["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError) as exc:
        raise EmbeddingUnavailableError(
            "gateway embedding response had no data[0].embedding"
        ) from exc
    if not isinstance(data, list):
        raise EmbeddingUnavailableError("gateway embedding was not a list of floats")
    return [float(value) for value in data]


def build_embedder(settings: Any) -> Embedder:
    """Pick the embedder from `Settings` (`SUNIL_MEMORY_EMBEDDER`).

    `hashing` is the default because it is the only one that works with no
    credential, and a memory provider that cannot boot without an embedding key
    would take the whole assistant down for a degraded-quality feature.
    """
    selected = getattr(settings, "sunil_memory_embedder", "hashing")
    if selected == "hashing":
        return HashingEmbedder()

    key = getattr(settings, "sunil_memory_embedding_api_key", None)
    if key is None or not key.get_secret_value():
        raise EmbeddingUnavailableError(
            "SUNIL_MEMORY_EMBEDDER='gateway' needs SUNIL_MEMORY_EMBEDDING_API_KEY "
            "(the gateway virtual key used for embedding calls). Refusing to boot "
            "rather than silently downgrading to lexical hashing — a deployment "
            "that asked for semantic recall must not get lexical recall quietly."
        )
    return GatewayEmbedder(
        base_url=settings.sunil_llm_gateway_base_url,
        model=settings.sunil_memory_embedding_model,
        api_key=key.get_secret_value(),
    )
