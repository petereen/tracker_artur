from app.services.ai_gateway.cache import exact_key
from app.services.ai_gateway.config import QueryCategory, registry
from app.services.ai_gateway.gateway import AIGateway, Classification


def test_default_registry_covers_each_supported_category():
    config = registry()
    assert set(config.routes) == set(QueryCategory)
    assert config.routes[QueryCategory.SIMPLE_QA] == ["luna", "terra", "sol"]
    assert config.routes[QueryCategory.CODE_GENERATION] == ["sol", "terra"]
    assert config.output_budgets[QueryCategory.SIMPLE_QA] == 600


def test_classifier_contract_requires_live_routing_fields():
    parsed = Classification.model_validate({
        "category": "simple_qa", "language": "mn", "requires_freshness": False,
        "requires_enterprise_tools": False, "requested_modalities": ["text"],
        "cache_eligible": True,
    })
    assert parsed.cache_eligible is True
    assert parsed.category is QueryCategory.SIMPLE_QA


def test_exact_cache_key_is_stable_for_whitespace_only_changes():
    assert exact_key(prompt_version="v1", language="mn", text="сайн байна уу") == exact_key(
        prompt_version="v1", language="mn", text="  сайн   байна уу  "
    )


def test_history_is_trimmed_from_oldest_turns_without_touching_latest_turn():
    gateway = AIGateway()
    history = [
        {"role": "user", "content": "old " * 100},
        {"role": "assistant", "content": "new"},
    ]
    assert gateway._trim_history(history, 20) == [{"role": "assistant", "content": "new"}]
