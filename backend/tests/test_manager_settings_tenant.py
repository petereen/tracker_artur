"""Management Telegram settings are per tenant and accept Telegram IDs only."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.tenancy import tenant_scope
from app.models.models import ManagerSettings
from app.routers import manager


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDB:
    def __init__(self, row=None):
        self.row = row
        self.added = []
        self.queries = []

    async def execute(self, query):
        self.queries.append(str(query))
        return _Result(self.row)

    def add(self, row):
        self.added.append(row)
        self.row = row

    async def commit(self):
        pass

    async def refresh(self, _row):
        pass


def test_settings_row_is_created_for_the_callers_tenant():
    db = FakeDB()
    with tenant_scope(7):
        asyncio.run(manager.update_settings(manager.ManagerSettingsUpdate(telegram_admin_ids=[" 123 ", "123", "456"]), db, None))
    row = db.added[0]
    assert isinstance(row, ManagerSettings) and row.organization_id == 7
    assert row.telegram_admin_ids == ["123", "456"] and row.telegram_id == "123" and row.telegram_username is None
    assert "manager_settings.organization_id" in db.queries[0]


@pytest.mark.parametrize("value", ["@boss", "boss", "12a4"])
def test_usernames_are_not_accepted_as_recipients(value):
    with tenant_scope(7), pytest.raises(HTTPException) as error:
        asyncio.run(manager.update_settings(manager.ManagerSettingsUpdate(telegram_admin_ids=[value]), FakeDB(ManagerSettings(organization_id=7)), None))
    assert error.value.status_code == 422 and error.value.detail["code"] == "telegram_id_invalid"
