"""Chat unread badges against PostgreSQL (runs only with SHARE_TEST_DATABASE_URL)."""

from __future__ import annotations

import asyncio
import uuid

from tests.test_chat_share_and_report_insights_db import _api, _ok, pytestmark  # noqa: F401


async def _send(client, conversation_id: str, body: str) -> dict:
    return await _ok(await client.post(f"/v1/chat/conversations/{conversation_id}/messages", json={"body": body, "client_nonce": str(uuid.uuid4())}))


async def _unread(client, conversation_id: str) -> tuple[int, int]:
    total = (await _ok(await client.get("/v1/chat/unread-count")))["unread_count"]
    single = (await _ok(await client.get(f"/v1/chat/conversations/{conversation_id}")))["unread_count"]
    return total, single


def test_reading_latest_message_clears_every_badge():
    async def run():
        async with _api() as (client, as_, _ids, _refs, conversations):
            direct = conversations["saraa_dorj"]
            as_("saraa")
            await _send(client, direct, "Сайн уу")
            latest = await _send(client, direct, "Тайлан бэлэн үү?")
            as_("dorj")
            assert await _unread(client, direct) == (2, 2)
            listed = await _ok(await client.get("/v1/chat/conversations", params={"filter": "unread"}))
            assert [item["public_id"] for item in listed["items"]] == [direct]
            await _ok(await client.post(f"/v1/chat/conversations/{direct}/receipts", json={"message_id": latest["id"], "status": "read"}))
            assert await _unread(client, direct) == (0, 0)
            assert not (await _ok(await client.get("/v1/chat/conversations", params={"filter": "unread"})))["items"]

    asyncio.run(run())


def test_rejoined_member_is_not_stuck_with_hidden_unread_messages():
    async def run():
        async with _api() as (client, as_, ids, _refs, _conversations):
            as_("bold")
            group = await _ok(await client.post("/v1/chat/conversations/groups", json={"title": "Баг", "member_account_ids": [ids["saraa_account"], ids["dorj_account"]]}))
            group_id = group["public_id"]
            await _send(client, group_id, "Өглөөний мэнд")  # dorj never reads this one
            await _ok(await client.delete(f"/v1/chat/conversations/{group_id}/members/{ids['dorj_account']}"))
            await _ok(await client.post(f"/v1/chat/conversations/{group_id}/members", json={"account_ids": [ids["dorj_account"]]}))
            as_("dorj")
            # The pre-rejoin message is hidden from dorj, so it cannot count.
            assert await _unread(client, group_id) == (0, 0)
            as_("bold")
            latest = await _send(client, group_id, "Тавтай морил")
            as_("dorj")
            assert await _unread(client, group_id) == (1, 1)
            await _ok(await client.post(f"/v1/chat/conversations/{group_id}/receipts", json={"message_id": latest["id"], "status": "read"}))
            assert await _unread(client, group_id) == (0, 0)

    asyncio.run(run())
