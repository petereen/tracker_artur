import asyncio

from app.services.ai_gateway.cache import exact_key
from app.services.ai_gateway.config import QueryCategory, registry
from app.services.ai_gateway.gateway import (
    AIGateway,
    Classification,
    CLASSIFICATION_SCHEMA,
    EXPLICIT_PROMPT_CACHE_TTL,
    GatewayRequest,
)


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


def test_explicit_prompt_cache_uses_provider_supported_ttl():
    assert EXPLICIT_PROMPT_CACHE_TTL == "30m"


def test_freshness_language_repair_does_not_keep_removed_web_tool_choice(monkeypatch):
    gateway = AIGateway()
    posted = []

    class Cache:
        async def circuit_open(self, _key):
            return False

        async def record_model_success(self, _key):
            return None

        async def record_model_failure(self, _key):
            return None

    gateway.cache = Cache()

    async def classify(_text):
        return Classification(
            category="simple_qa",
            language="mn",
            requires_freshness=True,
            requires_enterprise_tools=False,
            requested_modalities=["text"],
            cache_eligible=False,
        )

    async def post(payload, *, model_key, retries=2):
        del model_key, retries
        posted.append(payload)
        if len(posted) == 1:
            assert payload["tool_choice"] == {"type": "web_search"}
            return {
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "English answer"}]}],
                "usage": {},
            }
        assert payload["tools"] == []
        assert "tool_choice" not in payload
        return {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "Монгол хариу"}]}],
            "usage": {},
        }

    monkeypatch.setattr(gateway, "_classify", classify)
    monkeypatch.setattr(gateway, "_post", post)
    response = asyncio.run(gateway.respond(None, GatewayRequest(
        text="What is the latest company update?",
        history=[],
        channel="web",
    )))

    assert response.answer == "Монгол хариу"
    assert len(posted) == 2


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


def test_tool_enabled_turn_keeps_enterprise_tools_when_classifier_misses_route(monkeypatch):
    """A misclassified task request must still be able to prepare its draft."""
    gateway = AIGateway()
    calls = []

    class Cache:
        async def circuit_open(self, _key):
            return False

        async def record_model_success(self, _key):
            return None

        async def record_model_failure(self, _key):
            return None

    gateway.cache = Cache()

    async def classify(_text):
        return Classification(
            category="simple_qa",
            language="mn",
            requires_freshness=False,
            requires_enterprise_tools=False,
            requested_modalities=["text"],
            cache_eligible=True,
        )

    async def post(payload, *, model_key, retries=2):
        del model_key, retries
        if any(item.get("type") == "function_call_output" for item in payload["input"]):
            return {
                "output": [{
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Даалгаврын ноорог бэлэн боллоо."}],
                }],
                "usage": {},
            }
        return {
            "output": [{
                "type": "function_call",
                "name": "create_task",
                "call_id": "call-1",
                "arguments": '{"title":"Маргаашийн хурал","assignee":"self","description":null,"reviewer":null,"priority":2,"deadline_at":null,"project_ref":null}',
            }],
        }

    async def execute(name, arguments):
        calls.append((name, arguments))
        return {"status": "ok", "data": {"pending_action": {"title": arguments["title"]}}}

    monkeypatch.setattr(gateway, "_classify", classify)
    monkeypatch.setattr(gateway, "_post", post)
    response = asyncio.run(gateway.respond(
        None,
        GatewayRequest(
            text="Маргаашийн хурлыг даалгавар болго",
            history=[],
            channel="web",
            tools=[{"type": "function", "name": "create_task", "parameters": {}}],
            execute_tool=execute,
        ),
    ))

    assert calls[0][0] == "create_task"
    assert calls[0][1]["assignee"] == "self"
    assert response.answer == "Даалгаврын ноорог бэлэн боллоо."
