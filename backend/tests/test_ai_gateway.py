import asyncio
import json

import pytest

from app.core.enterprise_deps import ActorContext, permissions_for_roles
from app.services.ai_gateway.cache import exact_key
from app.services.ai_gateway.gateway import (
    ANSWER_SYSTEM,
    EXPLICIT_PROMPT_CACHE_TTL,
    AIGateway,
    GatewayError,
    GatewayRequest,
    memory_digest,
)
from app.services.ai_gateway.runtime import AIRuntime


def actor(role: str = "member", **overrides) -> ActorContext:
    roles = frozenset({role})
    values = dict(account_id=7, organization_id=3, employee_id=9, email="person@example.test", locale="mn", roles=roles, permissions=permissions_for_roles(roles), detected_language="mn", channel="web")
    values.update(overrides)
    return ActorContext(**values)


def runtime(**overrides) -> AIRuntime:
    values = dict(api_key="sk-test", primary_model="gpt-5.6-luna", fallback_model="gpt-5.6-terra", reasoning_effort="low", max_output_tokens=2_000, web_search_enabled=True, source="organization")
    values.update(overrides)
    return AIRuntime(**values)


class Cache:
    def __init__(self):
        self.failures = []

    async def circuit_open(self, _key):
        return False

    async def record_model_success(self, _key):
        return None

    async def record_model_failure(self, key):
        self.failures.append(key)


def message(text: str) -> dict:
    return {"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}], "usage": {"input_tokens": 10}}


def gateway_with(posts: list, replies: list) -> AIGateway:
    gateway = AIGateway()
    gateway.cache = Cache()

    async def post(payload, *, api_key, model_key, retries=2, stage="answer"):
        assert api_key == "sk-test"
        posts.append(json.loads(json.dumps(payload, default=str)))
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    gateway._post = post
    return gateway


def request(text: str, **overrides) -> GatewayRequest:
    values = dict(text=text, history=[], channel="web", actor_context=actor(), runtime=runtime(), grounding_context={"current_time": "2026-09-28T10:00:00+08:00", "timezone": "Asia/Ulaanbaatar"})
    values.update(overrides)
    return GatewayRequest(**values)


def test_raw_responses_items_are_converted_to_output_text():
    assert AIGateway._output_text({
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "hello"}, {"type": "output_text", "text": " world"}]}],
    }) == "hello world"


def test_explicit_prompt_cache_uses_provider_supported_ttl():
    assert EXPLICIT_PROMPT_CACHE_TTL == "30m"


def test_exact_cache_key_is_stable_for_whitespace_only_changes():
    assert exact_key(prompt_version="v1", language="mn", text="сайн байна уу") == exact_key(prompt_version="v1", language="mn", text="  сайн   байна уу  ")


def test_history_is_trimmed_from_oldest_turns_without_touching_latest_turn():
    gateway = AIGateway()
    history = [{"role": "user", "content": "old " * 100}, {"role": "assistant", "content": "new"}]
    assert gateway._trim_history(history, 20) == [{"role": "assistant", "content": "new"}]


def test_today_questions_never_force_web_search():
    """'Today' used to force tool_choice=web_search, hiding company data."""
    posts = []
    gateway = gateway_with(posts, [message("Өнөөдөр 2 даалгавар байна.")])
    response = asyncio.run(gateway.respond(None, request("өнөөдөр миний даалгавар юу вэ")))
    assert response.answer == "Өнөөдөр 2 даалгавар байна."
    assert "tool_choice" not in posts[0]
    names = {tool.get("name") or tool["type"] for tool in posts[0]["tools"]}
    assert {"oyuns_tasks_search", "oyuns_exchange_rate_get", "web_search"} <= names


def test_task_previews_are_visible_without_keyword_routing():
    posts = []
    gateway = gateway_with(posts, [message("ok")])
    asyncio.run(gateway.respond(None, request("Батад маргааш тайлан бэлдэхийг даалга")))
    names = {tool.get("name") for tool in posts[0]["tools"]}
    assert {"oyuns_tasks_prepare_create", "oyuns_tasks_prepare_update"} <= names


def test_single_model_call_without_router_round_trip():
    posts = []
    gateway = gateway_with(posts, [message("Сайн байна уу! Юугаар туслах вэ?")])
    asyncio.run(gateway.respond(None, request("сайн уу")))
    assert len(posts) == 1
    assert posts[0]["model"] == "gpt-5.6-luna"
    assert posts[0]["instructions"] == ANSWER_SYSTEM


def test_grounding_message_invites_tool_use_instead_of_refusal():
    posts = []
    gateway = gateway_with(posts, [message("ok")])
    asyncio.run(gateway.respond(None, request("компанийн дүрэм")))
    grounding = posts[0]["input"][0]["content"]
    assert "Call tools when it is not enough" in grounding
    assert "does not contain it" not in grounding


def test_sensitive_tools_are_hidden_when_not_allowed():
    posts = []
    gateway = gateway_with(posts, [message("ok"), message("ok")])
    admin = actor("admin")
    asyncio.run(gateway.respond(None, request("цалин", actor_context=admin)))
    asyncio.run(gateway.respond(None, request("цалин", actor_context=admin, sensitive_allowed=False)))
    first = {tool.get("name") for tool in posts[0]["tools"]}
    second = {tool.get("name") for tool in posts[1]["tools"]}
    assert "oyuns_payroll_summary" in first
    assert "oyuns_payroll_summary" not in second


def test_hidden_tool_call_is_denied_by_the_executor():
    gateway = AIGateway()
    req = request("цалин", actor_context=actor("admin"), sensitive_allowed=False)
    _, allowed = gateway._tool_catalog(req)
    result = asyncio.run(gateway._local_executor(req, allowed)("oyuns_payroll_summary", {}))
    assert result["status"] == "denied"


def test_fallback_model_answers_when_primary_fails():
    posts = []
    gateway = gateway_with(posts, [GatewayError("down", kind="provider_5xx", retryable=True), message("fallback answer")])
    response = asyncio.run(gateway.respond(None, request("hello there", actor_context=actor(detected_language="en"))))
    assert response.answer == "fallback answer"
    assert [item["model"] for item in posts] == ["gpt-5.6-luna", "gpt-5.6-terra"]
    assert gateway.cache.failures == ["gpt-5.6-luna"]


def test_custom_model_400_retries_once_with_minimal_payload():
    posts = []
    gateway = gateway_with(posts, [GatewayError("bad param", status_code=400, kind="provider_rejected"), message("ok")])
    response = asyncio.run(gateway.respond(None, request("hi", runtime=runtime(primary_model="gpt-5-mini", fallback_model=None))))
    assert response.answer == "ok"
    assert "reasoning" in posts[0] and "reasoning" not in posts[1]
    assert all(tool["type"] != "web_search" for tool in posts[1]["tools"])


def test_non_reasoning_models_do_not_receive_reasoning_parameters():
    posts = []
    gateway = gateway_with(posts, [message("ok")])
    asyncio.run(gateway.respond(None, request("hi", runtime=runtime(primary_model="gpt-4.1-mini"))))
    assert "reasoning" not in posts[0] and "text" not in posts[0]


def test_incomplete_empty_response_is_retried_with_more_output_room():
    posts = []
    gateway = gateway_with(posts, [{"status": "incomplete", "output": [{"type": "reasoning"}]}, message("complete")])
    response = asyncio.run(gateway.respond(None, request("summarize")))
    assert response.answer == "complete"
    assert posts[1]["max_output_tokens"] == 4_000


def test_tool_results_become_follow_up_memory():
    posts = []
    replies = [
        {"output": [{"type": "function_call", "name": "oyuns_tasks_search", "call_id": "c1", "arguments": "{}"}]},
        message("Танд 1 даалгавар байна."),
    ]
    gateway = gateway_with(posts, replies)

    async def execute(_name, _arguments):
        return {"status": "ok", "data": {"items": [{"title": "Тайлан", "reference": "ref-1", "status": "to_do"}]}}

    gateway._local_executor = lambda *_args: execute
    response = asyncio.run(gateway.respond(None, request("миний даалгавар")))
    assert response.memory == [{"tool": "oyuns_tasks_search", "items": [{"title": "Тайлан", "reference": "ref-1"}]}]
    assert posts[1]["input"][-1]["type"] == "function_call_output"


def test_skipped_second_preview_still_gets_a_function_output():
    posts = []
    replies = [
        {"output": [
            {"type": "function_call", "name": "oyuns_tasks_prepare_update", "call_id": "c1", "arguments": "{}"},
            {"type": "function_call", "name": "oyuns_tasks_prepare_update", "call_id": "c2", "arguments": "{}"},
        ]},
        message("done"),
    ]
    gateway = gateway_with(posts, replies)

    async def execute(_name, _arguments):
        return {"status": "empty", "data": {}}

    gateway._local_executor = lambda *_args: execute
    asyncio.run(gateway.respond(None, request("update both")))
    outputs = [item["call_id"] for item in posts[1]["input"] if item.get("type") == "function_call_output"]
    assert outputs == ["c1", "c2"]


def test_memory_digest_is_reference_only_and_bounded():
    digest = memory_digest([("oyuns_tasks_search", {"status": "ok", "data": {"items": [{"title": f"Task {index}", "reference": "r", "description": "secret"} for index in range(40)]}})])
    assert len(digest[0]["items"]) == 10
    assert "description" not in digest[0]["items"][0]
    assert memory_digest([("oyuns_tasks_search", {"status": "denied", "data": {}})]) == []


def test_missing_key_fails_as_not_configured_without_calling_the_provider():
    gateway = AIGateway()
    gateway.cache = Cache()
    with pytest.raises(GatewayError) as error:
        asyncio.run(gateway.respond(None, request("hi", actor_context=None, runtime=runtime(api_key=""))))
    assert error.value.kind == "not_configured"
