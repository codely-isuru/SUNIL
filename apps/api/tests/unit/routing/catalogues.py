"""In-memory catalogue fixtures for the routing unit tests.

These build REAL ``ModelCatalogue`` objects through ``from_mapping`` — the same
code path ``ModelCatalogue.load()`` uses after parsing YAML — so a routing test
exercises the production loader, not a stand-in for it. Only the *data* is
test-owned.
"""

from __future__ import annotations

from typing import Any

from sunil.core.routing.catalogue import ModelCatalogue


def fake_only_mapping(**overrides: Any) -> dict[str, Any]:
    """A catalogue with ONE non-local provider (``fake``) — the shape C2
    contract test 5 needs: no provider is flagged ``local: true``, so a
    ``LOCAL_ONLY`` request has nowhere to go."""
    mapping: dict[str, Any] = {
        "version": 1,
        "pricing_version": "test-1",
        "providers": {"fake": {"local": False, "lane": "prod"}},
        "models": {
            "claude-sonnet": {
                "provider": "fake",
                "provider_model_id": "fake-upstream-1",
                "context_window": 200000,
                "max_output": 64000,
                "input_usd_per_mtok": "1",
                "output_usd_per_mtok": "1",
                "supports_structured_output": True,
            }
        },
        "capabilities": {
            "general_reasoning": {
                "model": "claude-sonnet",
                "max_tokens": 4096,
                "timeout_s": 30.0,
            }
        },
    }
    mapping.update(overrides)
    return mapping


def fake_only() -> ModelCatalogue:
    return ModelCatalogue.from_mapping(fake_only_mapping())


def with_local_and_dev_providers() -> ModelCatalogue:
    """Adds a ``local: true`` provider and a PUBLIC-capped dev-lane provider so
    both privacy rules of C2 §2 have a positive and a negative case."""
    mapping = fake_only_mapping()
    mapping["providers"] = {
        "fake": {"local": False, "lane": "prod"},
        "fake_local": {"local": True, "lane": "prod"},
        "omniroute": {"local": False, "lane": "dev", "max_privacy_class": "public"},
    }
    mapping["models"]["claude-haiku"] = {
        "provider": "fake_local",
        "provider_model_id": "fake-local-1",
        "context_window": 8192,
        "max_output": 4096,
        "input_usd_per_mtok": "0",
        "output_usd_per_mtok": "0",
        "supports_structured_output": True,
    }
    mapping["models"]["gpt-mini"] = {
        "provider": "omniroute",
        "provider_model_id": "auto",
        "context_window": 8192,
        "max_output": 4096,
        "input_usd_per_mtok": "0",
        "output_usd_per_mtok": "0",
        "supports_structured_output": False,
    }
    mapping["capabilities"]["local_reasoning"] = {
        "model": "claude-haiku",
        "max_tokens": 1024,
        "timeout_s": 10.0,
    }
    mapping["capabilities"]["dev_experiment"] = {
        "model": "gpt-mini",
        "max_tokens": 1024,
        "timeout_s": 10.0,
    }
    return ModelCatalogue.from_mapping(mapping)
