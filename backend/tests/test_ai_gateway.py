from app.services.ai_gateway.cache import exact_key
from app.services.ai_gateway.config import QueryCategory, registry
from app.services.ai_gateway.gateway import AIGateway, Classification, CLASSIFICATION_SCHEMA


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


def test_classifier_schema_is_a_strict_responses_api_object():
    assert CLASSIFICATION_SCHEMA["type"] == "object"
    assert CLASSIFICATION_SCHEMA["additionalProperties"] is False
    assert set(CLASSIFICATION_SCHEMA["required"]) == set(CLASSIFICATION_SCHEMA["properties"])
    assert CLASSIFICATION_SCHEMA["properties"]["category"]["enum"] == [
        category.value for category in QueryCategory
    ]


def test_raw_responses_items_are_converted_to_output_text():
    assert AIGateway._output_text({
        "output": [{
            "type": "message",
            "content": [
                {"type": "output_text", "text": "hello"},
                {"type": "output_text", "text": " world"},
            ],
        }],
    }) == "hello world"


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
