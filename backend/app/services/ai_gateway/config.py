"""Validated model registry and bounded token policy.

The registry deliberately describes capabilities rather than routing with text
heuristics.  Deployments may replace it through AI_MODEL_REGISTRY_JSON.
"""
from __future__ import annotations

import json
from enum import Enum
from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings


class QueryCategory(str, Enum):
    SIMPLE_QA = "simple_qa"
    COMPLEX_REASONING = "complex_reasoning"
    CODE_GENERATION = "code_generation"
    MULTIMODAL = "multimodal"


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    modalities: set[str] = {"text", "image"}
    context_window: int = 1_050_000
    max_output_tokens: int = 128_000
    supports_web_search: bool = True
    supports_tools: bool = True
    reasoning_effort: str = "none"


class GatewayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = "v1"
    models: dict[str, ModelConfig]
    routes: dict[QueryCategory, list[str]]
    input_budgets: dict[QueryCategory, int]
    output_budgets: dict[QueryCategory, int]


DEFAULT = GatewayConfig(
    models={
        "luna": ModelConfig(id="gpt-5.6-luna", reasoning_effort="none"),
        "terra": ModelConfig(id="gpt-5.6-terra", reasoning_effort="medium"),
        "sol": ModelConfig(id="gpt-5.6-sol", reasoning_effort="medium"),
    },
    routes={
        QueryCategory.SIMPLE_QA: ["luna", "terra", "sol"],
        QueryCategory.COMPLEX_REASONING: ["terra", "sol", "luna"],
        QueryCategory.CODE_GENERATION: ["sol", "terra"],
        QueryCategory.MULTIMODAL: ["terra", "sol"],
    },
    input_budgets={
        QueryCategory.SIMPLE_QA: 16_000,
        QueryCategory.COMPLEX_REASONING: 64_000,
        QueryCategory.CODE_GENERATION: 96_000,
        QueryCategory.MULTIMODAL: 32_000,
    },
    output_budgets={
        QueryCategory.SIMPLE_QA: 600,
        QueryCategory.COMPLEX_REASONING: 2_500,
        QueryCategory.CODE_GENERATION: 4_000,
        QueryCategory.MULTIMODAL: 1_200,
    },
)


@lru_cache(maxsize=1)
def registry() -> GatewayConfig:
    raw = settings.AI_MODEL_REGISTRY_JSON.strip()
    if not raw:
        return DEFAULT
    return GatewayConfig.model_validate(json.loads(raw))
