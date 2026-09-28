"""Environment default models for OYUNS.

Organizations override these in platform settings (see ``runtime.py``).
Deployments may replace the defaults through AI_MODEL_REGISTRY_JSON; legacy
keys from the former router (routes, token budgets) are accepted and ignored.
"""
from __future__ import annotations

import json
from functools import lru_cache

from pydantic import BaseModel, ConfigDict

from app.core.config import settings


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str


class GatewayConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    version: str = "v1"
    models: dict[str, ModelConfig]


DEFAULT = GatewayConfig(
    models={
        "luna": ModelConfig(id="gpt-5.6-luna"),
        "terra": ModelConfig(id="gpt-5.6-terra"),
    },
)


@lru_cache(maxsize=1)
def registry() -> GatewayConfig:
    raw = settings.AI_MODEL_REGISTRY_JSON.strip()
    if not raw:
        return DEFAULT
    return GatewayConfig.model_validate(json.loads(raw))
