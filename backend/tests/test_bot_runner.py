"""The bot runner polls every tenant's bot and follows connects/disconnects."""

import asyncio

import pytest
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.methods import GetUpdates
from aiogram.types import Update

from app.bot import main as runner
from app.services.telegram_bots import TenantBot

TOKEN_A = "111111:" + "A" * 35
TOKEN_B = "222222:" + "B" * 35


class FakeSession:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class FakeBot:
    instances: list["FakeBot"] = []
    script: dict[str, list] = {}

    def __init__(self, token, default=None):
        self.token = token
        self.id = int(token.split(":")[0])
        self.session = FakeSession()
        self.polls = 0
        FakeBot.instances.append(self)

    async def delete_webhook(self, drop_pending_updates=False):
        return True

    async def get_updates(self, **kwargs):
        self.polls += 1
        steps = FakeBot.script.get(self.token, [])
        if steps:
            step = steps.pop(0)
            if isinstance(step, Exception):
                raise step
            return step
        await asyncio.sleep(3600)


class FakeDispatcher:
    def __init__(self):
        self.fed = []

    def resolve_used_update_types(self):
        return ["message"]

    async def feed_update(self, bot, update, **kwargs):
        self.fed.append((bot.id, update.update_id, kwargs))


@pytest.fixture
def pool(monkeypatch):
    FakeBot.instances = []
    FakeBot.script = {}
    monkeypatch.setattr(runner, "Bot", FakeBot)

    async def no_menus(*args, **kwargs):
        return None

    monkeypatch.setattr(runner, "setup_bot_menus", no_menus)
    monkeypatch.setattr(runner, "is_primary_tenant", lambda organization_id: organization_id == 1)
    monkeypatch.setattr(runner.telegram_bots, "mini_app_url_sync", lambda organization_id: "")
    seen = []
    errors = []
    monkeypatch.setattr(runner.telegram_bots, "record_bot_seen_sync", lambda ids: seen.append(sorted(ids)))
    monkeypatch.setattr(runner.telegram_bots, "record_bot_error_sync", lambda bot_id, message, disable=False: errors.append((bot_id, disable)))
    registry_state = {"bots": []}
    monkeypatch.setattr(runner.telegram_bots.registry, "load_sync", lambda: registry_state["bots"])
    dispatcher = FakeDispatcher()
    return runner.BotPool(dispatcher), dispatcher, registry_state, seen, errors


def test_pool_feeds_updates_with_the_bot_tenant_and_follows_the_registry(pool):
    bot_pool, dispatcher, registry_state, seen, _ = pool
    FakeBot.script = {TOKEN_A: [[Update(update_id=5)]], TOKEN_B: [[Update(update_id=9)]]}
    registry_state["bots"] = [TenantBot(2, 111111, TOKEN_A, "a", "active", "tenant"), TenantBot(1, 222222, TOKEN_B, None, "active", "platform")]

    async def scenario():
        await bot_pool.sync()
        await asyncio.sleep(0.05)
        await bot_pool.sync()
        assert sorted(dispatcher.fed, key=lambda item: item[0]) == [
            (111111, 5, {"bot_tenant_id": 2}),
            (222222, 9, {"bot_tenant_id": 1}),
        ]
        # Heartbeats only for tenant bots that polled successfully.
        assert seen[-1] == [111111]
        # Disconnecting a tenant stops its polling and closes the client.
        registry_state["bots"] = registry_state["bots"][1:]
        await bot_pool.sync()
        assert set(bot_pool.running) == {222222}
        assert FakeBot.instances[0].session.closed
        await bot_pool.stop_all()

    asyncio.run(scenario())


def test_revoked_token_marks_the_bot_and_is_not_restarted(pool):
    bot_pool, _, registry_state, _, errors = pool
    FakeBot.script = {TOKEN_A: [TelegramUnauthorizedError(method=GetUpdates(), message="Unauthorized")]}
    registry_state["bots"] = [TenantBot(2, 111111, TOKEN_A, "a", "active", "tenant")]

    async def scenario():
        await bot_pool.sync()
        await asyncio.sleep(0.05)
        assert errors == [(111111, True)]
        await bot_pool.sync()  # the dead task is cleaned up and not restarted
        assert 111111 not in bot_pool.running
        assert len(FakeBot.instances) == 1
        await bot_pool.stop_all()

    asyncio.run(scenario())
