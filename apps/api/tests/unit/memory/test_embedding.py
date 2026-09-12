"""The `Embedder` seam — C3 §2's "embeddings are obtained through the gateway",
with a deterministic local embedder underneath the test suite.

Two implementations, one protocol:

* ``HashingEmbedder`` — no network, no key, no model. Bag-of-words hashed into
  buckets and L2-normalised, so cosine similarity is *monotone in token
  overlap*. That property is what makes it a legitimate stand-in for a real
  embedder in a behavioural test: the provider's ordering assertions are about
  "more relevant first", and this embedder makes "more relevant" mean something
  real rather than something rigged.
* ``GatewayEmbedder`` — the production one, POSTing to the LiteLLM gateway's
  OpenAI-compatible ``/v1/embeddings``. Tested here for request SHAPE and for
  its failure posture only; no key exists on this machine, so the live call is
  unproven and says so in its own docstring.

The dimension is schema, not configuration: the ``memories.embedding`` column is
``vector(1536)``, so an embedder of another width must fail LOUDLY at
construction rather than at the first INSERT.
"""

from __future__ import annotations

import json
import math

import httpx
import pytest

from sunil.core.memory.embedding import (
    EMBEDDING_DIM,
    Embedder,
    EmbeddingUnavailableError,
    GatewayEmbedder,
    HashingEmbedder,
)


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


# --------------------------------------------------------------------------- #
# HashingEmbedder — the deterministic local one
# --------------------------------------------------------------------------- #
async def test_hashing_embedder_is_deterministic_across_instances() -> None:
    """A test embedder whose vectors moved between runs would make every
    ordering assertion in the parity suite flaky-by-construction. Two separate
    instances must agree, because ``PYTHONHASHSEED`` randomises ``hash()`` per
    process and a naive implementation would inherit that."""
    first = await HashingEmbedder().embed("winch recovery training")
    second = await HashingEmbedder().embed("winch recovery training")

    assert first == second


async def test_hashing_embedder_width_is_the_schema_width() -> None:
    """``memories.embedding`` is ``vector(EMBEDDING_DIM)``."""
    vector = await HashingEmbedder().embed("anything")

    assert len(vector) == EMBEDDING_DIM
    assert HashingEmbedder().dimension == EMBEDDING_DIM


async def test_hashing_embedder_returns_unit_vectors() -> None:
    """L2-normalised, so the cosine distance pgvector computes IS the dot
    product and scores land in a comparable 0..1 band."""
    vector = await HashingEmbedder().embed("winch recovery training")

    assert math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0, rel_tol=1e-9)


async def test_similarity_is_monotone_in_token_overlap() -> None:
    """The property the parity suite leans on: a document sharing MORE query
    tokens scores higher than one sharing fewer, which scores higher than one
    sharing none."""
    embedder = HashingEmbedder()
    query = await embedder.embed("winch recovery")
    both = await embedder.embed("winch recovery training")
    one = await embedder.embed("winch only")
    none = await embedder.embed("entirely unrelated")

    assert cosine(query, both) > cosine(query, one) > cosine(query, none)
    assert math.isclose(cosine(query, none), 0.0, abs_tol=1e-12)


async def test_tokenisation_is_case_and_punctuation_insensitive() -> None:
    embedder = HashingEmbedder()

    assert await embedder.embed("Winch, Recovery.") == await embedder.embed("winch recovery")


async def test_empty_text_embeds_to_the_zero_vector() -> None:
    """A zero vector is cosine-undefined, which is exactly why the provider
    must treat an empty query as "no candidates" rather than dividing by it."""
    vector = await HashingEmbedder().embed("   ")

    assert vector == [0.0] * EMBEDDING_DIM


# --------------------------------------------------------------------------- #
# GatewayEmbedder — the production one
# --------------------------------------------------------------------------- #
async def test_gateway_embedder_posts_openai_shaped_body_and_returns_the_vector() -> None:
    """Request shape is assertable without a key; the live call is not (see the
    module docstring). ``/v1/embeddings`` on the LiteLLM gateway is the C2 §2
    routing/budget path for embeddings."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.read().decode())
        return httpx.Response(
            200, json={"data": [{"embedding": [0.0] * EMBEDDING_DIM, "index": 0}]}
        )

    embedder = GatewayEmbedder(
        base_url="http://litellm:4000",
        model="text-embedding-3-small",
        api_key="not-a-real-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    vector = await embedder.embed("winch recovery")

    assert len(vector) == EMBEDDING_DIM
    assert seen["url"] == "http://litellm:4000/v1/embeddings"
    assert seen["auth"] == "Bearer not-a-real-key"
    assert seen["body"] == {"model": "text-embedding-3-small", "input": "winch recovery"}


async def test_gateway_embedder_rejects_a_wrong_width_vector() -> None:
    """A model swap that silently changed width would write rows the
    ``vector(1536)`` column rejects — or, worse, be caught by nobody until the
    INSERT. Fail at the seam, naming both widths."""
    embedder = GatewayEmbedder(
        base_url="http://litellm:4000",
        model="text-embedding-3-large",
        api_key="not-a-real-key",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
            )
        ),
    )

    with pytest.raises(EmbeddingUnavailableError) as err:
        await embedder.embed("winch")

    assert "2" in str(err.value) and str(EMBEDDING_DIM) in str(err.value)


async def test_gateway_embedder_converts_transport_failure_into_one_named_error() -> None:
    """C3 §2's degrade posture starts here: the provider translates an embedding
    failure into ``MemoryUnavailableError``, which it can only do if the
    embedder raises ONE type rather than leaking httpx's."""
    embedder = GatewayEmbedder(
        base_url="http://litellm:4000",
        model="text-embedding-3-small",
        api_key="not-a-real-key",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(500, text="upstream exploded")
            )
        ),
    )

    with pytest.raises(EmbeddingUnavailableError):
        await embedder.embed("winch")


def test_both_embedders_satisfy_the_protocol() -> None:
    """Structural conformance, asserted rather than assumed."""
    local: Embedder = HashingEmbedder()
    remote: Embedder = GatewayEmbedder(
        base_url="http://litellm:4000", model="m", api_key="k"
    )

    assert local.dimension == remote.dimension == EMBEDDING_DIM
