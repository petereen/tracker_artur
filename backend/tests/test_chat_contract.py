import asyncio
import inspect
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.enterprise_deps import ActorContext, get_actor
from app.main import app
from app.models.models import Base, ChatAttachment, ChatConversation, ChatMessage, ChatMessageHidden, ChatMessagePin, ChatMessageReaction, ChatMessageReceipt, ChatMessageStar, ChatParticipant
from app.routers.chat import MessageIn, _clean_group_title, _file_signature_matches, _membership, acknowledge_receipts, open_direct, receipt_details


def actor(account_id: int = 1, organization_id: int = 7) -> ActorContext:
    return ActorContext(account_id=account_id, organization_id=organization_id, employee_id=10, email="member@example.com", locale="mn", roles=frozenset({"member"}))


def test_chat_schema_and_routes_are_registered():
    assert {"chat_conversations", "chat_participants", "chat_messages", "chat_message_receipts", "chat_attachments", "chat_message_reactions", "chat_message_stars", "chat_message_pins", "chat_message_hidden", "workspace_presence"}.issubset(Base.metadata.tables)
    paths = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    assert {
        ("/v1/chat/contacts", "GET"),
        ("/v1/chat/conversations", "GET"),
        ("/v1/chat/conversations/direct", "POST"),
        ("/v1/chat/conversations/groups", "POST"),
        ("/v1/chat/conversations/{public_id}/messages", "GET"),
        ("/v1/chat/conversations/{public_id}/messages", "POST"),
        ("/v1/chat/conversations/{public_id}/receipts", "POST"),
        ("/v1/chat/conversations/{public_id}/preferences", "PATCH"),
        ("/v1/chat/conversations/{public_id}/uploads", "POST"),
        ("/v1/chat/conversations/{public_id}/messages/{message_id}", "PATCH"),
        ("/v1/chat/conversations/{public_id}/messages/{message_id}", "DELETE"),
        ("/v1/chat/conversations/{public_id}/messages/{message_id}/thread", "GET"),
        ("/v1/chat/search", "GET"),
        ("/v1/chat/unread-count", "GET"),
    }.issubset(paths)


def test_chat_constraints_cover_direct_uniqueness_message_idempotency_and_receipts():
    conversation_constraints = {constraint.name for constraint in ChatConversation.__table__.constraints}
    participant_constraints = {constraint.name for constraint in ChatParticipant.__table__.constraints}
    message_constraints = {constraint.name for constraint in ChatMessage.__table__.constraints}
    receipt_constraints = {constraint.name for constraint in ChatMessageReceipt.__table__.constraints}
    assert "uq_chat_conversations_direct_key" in conversation_constraints
    assert "uq_chat_participants_conversation_account" in participant_constraints
    assert "uq_chat_messages_client_nonce" in message_constraints
    assert "ck_chat_messages_body_length" in message_constraints
    assert "company_file_attachments" in ChatMessage.__table__.columns
    assert "uq_chat_message_receipts_message_account" in receipt_constraints
    assert "ck_chat_message_receipts_read_delivered" in receipt_constraints
    assert "ix_chat_messages_thread_root" in {index.name for index in ChatMessage.__table__.indexes}
    assert "ck_chat_attachments_media_kind" in {constraint.name for constraint in ChatAttachment.__table__.constraints}
    assert "uq_chat_message_reaction_actor" in {constraint.name for constraint in ChatMessageReaction.__table__.constraints}
    assert "uq_chat_message_star_actor" in {constraint.name for constraint in ChatMessageStar.__table__.constraints}
    assert "uq_chat_message_pin" in {constraint.name for constraint in ChatMessagePin.__table__.constraints}
    assert "uq_chat_message_hidden_actor" in {constraint.name for constraint in ChatMessageHidden.__table__.constraints}


def test_message_and_group_title_validation_reject_empty_or_oversized_values():
    assert MessageIn(body="hello", client_nonce=uuid4()).body == "hello"
    with pytest.raises(ValidationError):
        MessageIn(body="x" * 4001, client_nonce=uuid4())
    with pytest.raises(HTTPException) as exc:
        _clean_group_title("   ")
    assert exc.value.status_code == 422
    assert _clean_group_title("  Product team  ") == "Product team"
    assert MessageIn(body=None, upload_ids=[uuid4()], client_nonce=uuid4()).body is None


def test_chat_upload_signatures_reject_disguised_executables_and_mismatched_media():
    assert _file_signature_matches("application/pdf", b"%PDF-1.7\n")
    assert _file_signature_matches("image/png", b"\x89PNG\r\n\x1a\ncontent")
    assert not _file_signature_matches("image/png", b"GIF89a-content")
    assert not _file_signature_matches("text/plain", b"MZ\x00\x00executable")


def test_chat_endpoints_use_authenticated_actor_and_author_only_receipts():
    assert inspect.signature(open_direct).parameters["actor"].default.dependency is get_actor
    assert inspect.signature(acknowledge_receipts).parameters["actor"].default.dependency is get_actor
    assert inspect.signature(receipt_details).parameters["actor"].default.dependency is get_actor


def test_missing_or_cross_tenant_membership_is_hidden_as_not_found():
    class Result:
        def one_or_none(self):
            return None

    class FakeDb:
        async def execute(self, _statement):
            return Result()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(_membership(FakeDb(), actor(), uuid4()))
    assert exc.value.status_code == 404


def test_only_group_owner_can_manage_membership():
    class Result:
        def one_or_none(self):
            return SimpleNamespace(kind="group"), SimpleNamespace(role="member")

    class FakeDb:
        async def execute(self, _statement):
            return Result()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(_membership(FakeDb(), actor(), uuid4(), owner=True))
    assert exc.value.status_code == 403
