from pathlib import Path

from app.main import app
from app.models.models import Base, ChatCall, ChatMessage


def test_call_tables_and_immutable_message_reference_are_registered():
    assert "chat_calls" in Base.metadata.tables
    assert ChatMessage.__table__.c.kind.server_default is not None
    assert ChatMessage.__table__.c.call_id.unique
    constraints = {item.name for item in ChatCall.__table__.constraints}
    assert {"ck_chat_calls_type", "ck_chat_calls_status", "ck_chat_calls_outcome", "ck_chat_calls_distinct_peers"}.issubset(constraints)


def test_call_session_authorization_and_internal_lifecycle_routes_exist():
    paths = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    assert {
        ("/v1/calls/session", "GET"),
        ("/v1/calls/authorize", "POST"),
        ("/v1/calls/internal/initiate", "POST"),
        ("/v1/calls/internal/{call_id}", "PATCH"),
    }.issubset(paths)


def test_call_migration_is_at_the_alembic_head():
    migration = Path(__file__).parents[1] / "alembic" / "versions" / "v1w2x3y4z5a6_chat_calls.py"
    source = migration.read_text()
    assert 'revision: str = "v1w2x3y4z5a6"' in source
    assert 'down_revision: Union[str, Sequence[str], None] = "u0v1w2x3y4z5"' in source
