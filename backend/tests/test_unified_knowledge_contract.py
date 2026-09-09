from app.services.ai_gateway.gateway import RoutingDecision
from app.services.file_search_service import build_lexical_query, like_pattern
from app.services.mcp.results import SanitizationPolicy, sanitize_result


def test_routing_decision_is_write_fail_closed():
    decision = RoutingDecision(model_key="luna", reasoning_effort="none", output_format="plain_text", verbosity="low")
    assert decision.action_intents == []


def test_lexical_query_and_like_pattern_are_bounded_and_escaped():
    assert build_lexical_query("what is wifi password") == "wifi | password"
    assert like_pattern("100%_safe") == "%100\\%\\_safe%"


def test_sanitizer_preserves_trusted_business_password_but_redacts_system_secrets():
    value = {"excerpt": "Wi-Fi password: Guest-2026! sk-proj-aaaaaaaaaaaaaaaaaaaaaaaa"}
    safe = sanitize_result(value, policy=SanitizationPolicy(trusted_operational_paths=frozenset({("excerpt",)})))
    assert "Guest-2026!" in safe["excerpt"]
    assert "sk-proj-" not in safe["excerpt"]
