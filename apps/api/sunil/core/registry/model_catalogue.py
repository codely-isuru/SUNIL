"""`config/models.yaml` — the model catalogue and capability map the Model
Router (T6) reads (`ARCHITECTURE_V1.md` §4.4, §4.5).

Named `model_catalogue`, not `models` — `sunil.db.models` already owns
that name for the ORM tables, and the owner's review renamed the Model
*Router* package away from `core/models/` to `core/routing/` for exactly
this class of collision (A-1, §2.1). This module is data about LLM models,
consumed by `core/routing/`; it is not the router itself.

Two sections: `models` is the pinned price/context table (§4.4), keyed by
exact snapshot model id; `capabilities` is the `capability -> {provider,
model, max_tokens, timeout_s}` lookup §4.5 describes, keyed by the
capability names an agent declares in `config/agents.yaml`
(`preferred_capability`, `escalation_capability`).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from sunil.core.registry._yaml import read_yaml
from sunil.core.registry.errors import (
    RegistrySchemaError,
    UnknownCapabilityError,
    UnknownModelError,
)


class ModelDefinition(BaseModel):
    """Shaped to match `providers/base.py`'s `ModelCapabilities` (§4.2) —
    T6 builds one from this at router-construction time."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str
    provider: str
    context_window: int
    max_output: int
    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal
    supports_structured_output: bool


class CapabilityDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: str
    provider: str
    model: str
    max_tokens: int
    timeout_s: float


class ModelRegistry:
    def __init__(
        self,
        pricing_version: str,
        models: dict[str, ModelDefinition],
        capabilities: dict[str, CapabilityDefinition],
    ) -> None:
        self.pricing_version = pricing_version
        self._models = models
        self._capabilities = capabilities

    def get_model(self, model_id: str) -> ModelDefinition:
        try:
            return self._models[model_id]
        except KeyError:
            raise UnknownModelError(model_id) from None

    def get_capability(self, capability: str) -> CapabilityDefinition:
        try:
            return self._capabilities[capability]
        except KeyError:
            raise UnknownCapabilityError(capability) from None

    def capability_names(self) -> list[str]:
        return list(self._capabilities.keys())

    def model_ids(self) -> list[str]:
        return list(self._models.keys())


def load_models(config_dir: Path) -> ModelRegistry:
    path = config_dir / "models.yaml"
    raw = read_yaml(path)

    version = raw.get("version")
    if version != 1:
        raise RegistrySchemaError(f"{path}: expected version: 1, found {version!r}")

    pricing_version = raw.get("pricing_version")
    if not pricing_version or not isinstance(pricing_version, str):
        raise RegistrySchemaError(
            f"{path}: 'pricing_version' is required (ARCHITECTURE_V1.md §4.4)"
        )

    models_raw = raw.get("models") or {}
    if not isinstance(models_raw, dict):
        raise RegistrySchemaError(f"{path}: 'models' must be a mapping")

    models: dict[str, ModelDefinition] = {}
    for model_id, body in models_raw.items():
        try:
            models[model_id] = ModelDefinition(model_id=model_id, **(body or {}))
        except Exception as exc:
            raise RegistrySchemaError(f"{path}: model {model_id!r} is invalid: {exc}") from exc

    capabilities_raw = raw.get("capabilities") or {}
    if not isinstance(capabilities_raw, dict):
        raise RegistrySchemaError(f"{path}: 'capabilities' must be a mapping")

    capabilities: dict[str, CapabilityDefinition] = {}
    for capability, body in capabilities_raw.items():
        try:
            capabilities[capability] = CapabilityDefinition(capability=capability, **(body or {}))
        except Exception as exc:
            raise RegistrySchemaError(
                f"{path}: capability {capability!r} is invalid: {exc}"
            ) from exc

    for capability, definition in capabilities.items():
        if definition.model not in models:
            raise RegistrySchemaError(
                f"{path}: capability {capability!r} points at unknown model {definition.model!r}"
            )

    if not models:
        raise RegistrySchemaError(f"{path}: no models defined")
    if not capabilities:
        raise RegistrySchemaError(f"{path}: no capabilities defined")

    return ModelRegistry(pricing_version=pricing_version, models=models, capabilities=capabilities)
