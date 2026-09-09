"""Exercise gateway recovery with real AsyncSession savepoints and ORM state."""
import asyncio
from dataclasses import replace

import pytest
from sqlalchemy import ForeignKey, Integer, String, event, inspect, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, mapped_column

from app.core.enterprise_deps import ActorContext
from app.services.ai_gateway import gateway as gateway_module
from app.services.ai_gateway.gateway import AIGateway, GatewayResponse, PreflightGrounding
from app.services.file_search_service import KnowledgeSearchResult


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "test_conversations"
    id = mapped_column(Integer, primary_key=True)
    title = mapped_column(String)


class Message(Base):
    __tablename__ = "test_messages"
    id = mapped_column(Integer, primary_key=True)
    conversation_id = mapped_column(ForeignKey(Conversation.id), nullable=False)
    content = mapped_column(String)


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("channel", ["web", "telegram"])
@pytest.mark.parametrize("failed_lookup", ["identity", "knowledge"])
def test_failed_optional_lookup_preserves_request(monkeypatch, tmp_path, existing, channel, failed_lookup):
    async def scenario():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'recovery.db'}")

        @event.listens_for(engine.sync_engine, "connect")
        def foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as db:
                conversation = Conversation(title="Meeting")
                db.add(conversation)
                await db.flush()
                conversation_id = conversation.id
                if existing:
                    await db.commit()
                db.add(Message(conversation_id=conversation_id, content="user request"))

                gateway = AIGateway()
                actor = ActorContext(1, 1, None, "test@example.test", "mn", frozenset({"member"}), channel=channel)
                original_get = db.get
                if failed_lookup == "identity":
                    actor = replace(actor, employee_id=9)

                    async def failing_get(model, key, **kwargs):
                        if model is gateway_module.Employee:
                            await db.execute(text("SELECT * FROM missing_identity_table"))
                        return await original_get(model, key, **kwargs)

                    monkeypatch.setattr(db, "get", failing_get)

                async def preflight(session, _actor, _text):
                    if failed_lookup == "knowledge":
                        await session.execute(text("SELECT * FROM missing_knowledge_table"))
                    return PreflightGrounding(KnowledgeSearchResult("empty", ()))

                async def respond(session, request):
                    assert request.channel == channel
                    assert request.conversation_id == conversation_id
                    assert inspect(conversation).persistent
                    assert not inspect(conversation).expired
                    assert conversation.title == "Meeting"
                    assert (await session.scalars(select(Message.content))).all() == ["user request"]
                    return GatewayResponse(answer="Reply", sources=[], route="test", model="test", cache="bypass", web_search_used=False, usage={})

                monkeypatch.setattr(gateway, "_preflight_grounding", preflight)
                monkeypatch.setattr(gateway, "respond", respond)
                response = await gateway.execute_turn(db, actor, [{"role": "user", "content": "user request"}], conversation_id=conversation_id)
                db.add(Message(conversation_id=conversation.id, content=response.answer))
                await db.commit()

            async with sessions() as db:
                assert await db.get(Conversation, conversation_id) is not None
                assert (await db.scalars(select(Message.content).order_by(Message.id))).all() == ["user request", "Reply"]
        finally:
            await engine.dispose()

    asyncio.run(scenario())
