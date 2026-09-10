"""Opt-in integration test: creates and removes only its own temporary schema."""
import asyncio
import os
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.enterprise_deps import build_actor_context
from app.models import models
from app.services.ai_gateway.gateway import AIGateway
from app.services.enterprise_tools import confirm_task_update


@pytest.mark.parametrize("channel", ["web", "telegram"])
def test_preview_confirm_reload_and_replay_in_postgres(monkeypatch, channel):
    database_url = os.getenv("OYUNS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set OYUNS_TEST_DATABASE_URL to an isolated PostgreSQL test database")

    async def scenario():
        schema = "assistant_test_" + uuid4().hex
        engine = create_async_engine(database_url, connect_args={"server_settings": {"search_path": schema}})
        roots = [models.AssistantConversation, models.AssistantMessage, models.AssistantPendingAction, models.AssistantToolAudit, models.Task, models.TaskAssignee, models.TaskReviewer, models.UserAccount, models.Employee, models.Organization, models.RoleAssignment, models.DomainEvent, models.AuditLog, models.ManagerSettings, models.UserNotification, models.NotificationOutbox]
        tables = set()

        def collect(table):
            if table in tables:
                return
            tables.add(table)
            for foreign_key in table.foreign_keys:
                collect(foreign_key.column.table)

        for root in roots:
            collect(root.__table__)
        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.run_sync(lambda conn: Base.metadata.create_all(conn, tables=list(tables)))
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as db:
                org = models.Organization(name="Integration test")
                db.add(org)
                await db.flush()
                employee = models.Employee(organization_id=org.id, name="Тэмүүлэн", timezone="Asia/Ulaanbaatar")
                db.add(employee)
                await db.flush()
                account = models.UserAccount(organization_id=org.id, employee_id=employee.id, email="test@example.test", password_hash="not-a-login", status="active")
                db.add(account)
                await db.flush()
                actor = build_actor_context(account_id=account.id, organization_id=org.id, employee_id=employee.id, email=account.email, locale="mn", roles=frozenset({"member"}), channel=channel)
                conversation = models.AssistantConversation(organization_id=org.id, account_id=account.id, channel=channel, title="Test")
                db.add(conversation)
                await db.flush()
                prompt = "би маргааш 16 цагаас хуралтай шүү даалгавар үүсгэ"
                db.add(models.AssistantMessage(conversation_id=conversation.id, role="user", content=prompt))
                gateway = AIGateway()

                async def forbidden(*_, **__):
                    pytest.fail("No external model or retrieval dependency for this request")

                monkeypatch.setattr(gateway, "_post", forbidden)
                monkeypatch.setattr(gateway, "_preflight_grounding", forbidden)
                response = await gateway.execute_turn(db, actor, [{"role": "user", "content": prompt}], conversation_id=conversation.id)
                assert response.route == "task_fast_path"
                pending = response.tool_results[0]["data"]["pending_action"]
                expected_start = datetime.fromisoformat(pending["start_at"])
                assert expected_start.astimezone(ZoneInfo(employee.timezone)).hour == 16
                assert pending["deadline_at"] is None
                db.add(models.AssistantMessage(conversation_id=conversation.id, role="assistant", content=response.answer))
                await db.commit()

            async with sessions() as db:
                result = await confirm_task_update(db, actor, pending["action_reference"], channel=channel)
                assert result["status"] == "ok", result
                await db.commit()
            async with sessions() as db:
                task = (await db.scalars(select(models.Task))).one()
                assert task.start_at == expected_start
                assert task.deadline_at is None
                assert task.assignee_id == actor.employee_id
                assert (await db.scalars(select(models.TaskAssignee.employee_id))).all() == [actor.employee_id]
                assert await db.scalar(select(func.count()).select_from(models.UserNotification)) == 1
                assert await db.scalar(select(func.count()).select_from(models.AssistantMessage)) == 2
                replay = await confirm_task_update(db, actor, pending["action_reference"], channel=channel)
                assert replay["data"]["replayed"] is True
                await db.commit()
                assert await db.scalar(select(func.count()).select_from(models.Task)) == 1
        finally:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await engine.dispose()

    asyncio.run(scenario())
