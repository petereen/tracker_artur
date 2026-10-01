"""Tenant rules + personal choices decide web and Telegram delivery."""
import pytest

from app.services.notification_preferences import (
    category_for,
    merge_user_choices,
    resolve,
    tenant_rules,
    user_choices,
    validate_tenant_input,
)


def settings(**categories):
    return {"notifications": {"categories": categories}}


def prefs(**categories):
    return {"notifications": {"categories": categories}}


@pytest.mark.parametrize("kind,category", [
    ("task_assigned", "tasks"), ("task_overdue", "tasks"), ("periodic_report", "reports"), ("report_submitted", "reports"),
    ("worktime_reminder", "worktime"), ("project_deadline", "calendar"), ("calendar_reminder", "calendar"),
    ("contract_signed", "contracts"), ("hr_leave_requested", "hr"), ("birthday", "hr"), ("crm_activity_due", "crm"),
    ("daily_checkin", "checkin"), ("task_digest", "digests"), ("something_new", "system"),
])
def test_every_kind_has_a_category(kind, category):
    assert category_for(kind) == category


def test_defaults_deliver_everything_except_the_legacy_checkin():
    assert resolve(None, None, "task_assigned").web and resolve(None, None, "task_assigned").telegram
    checkin = resolve(None, None, "daily_checkin")
    assert not checkin.web and not checkin.telegram


def test_legacy_checkin_cannot_be_enabled_outside_the_primary_tenant():
    enabled = settings(checkin={"enabled": True, "web": True, "telegram": True})
    assert resolve(enabled, None, "daily_checkin", legacy_available=True).telegram
    assert not resolve(enabled, None, "daily_checkin", legacy_available=False).telegram


def test_user_choices_override_tenant_defaults_only_where_editable():
    tenant = settings(tasks={"telegram": True}, crm={"user_editable": False})
    user = prefs(tasks={"telegram": False}, crm={"telegram": False, "web": False})
    assert resolve(tenant, user, "task_assigned").telegram is False
    assert resolve(tenant, user, "task_assigned").web is True
    # CRM is locked by the admin: the personal choice is ignored.
    assert resolve(tenant, user, "crm_activity_due").telegram is True


def test_tenant_switch_off_beats_personal_choices():
    tenant = settings(tasks={"enabled": False})
    user = prefs(tasks={"telegram": True, "web": True})
    delivery = resolve(tenant, user, "task_deadline")
    assert not delivery.web and not delivery.telegram


def test_tenant_default_off_can_be_opted_into_by_the_user():
    tenant = settings(digests={"telegram": False})
    assert resolve(tenant, None, "task_digest").telegram is False
    assert resolve(tenant, prefs(digests={"telegram": True}), "task_digest").telegram is True


def test_merge_stores_only_allowed_choices():
    rules = tenant_rules(settings(crm={"user_editable": False}, hr={"enabled": False}))
    merged = merge_user_choices({"chat_notifications": {"sound_enabled": True}}, rules, {
        "tasks": {"telegram": False}, "crm": {"telegram": False}, "hr": {"web": False},
    })
    assert merged["chat_notifications"] == {"sound_enabled": True}
    assert user_choices(merged) == {"tasks": {"telegram": False}}
    with pytest.raises(ValueError):
        merge_user_choices(None, rules, {"nope": {"web": True}})


def test_tenant_input_is_validated():
    assert validate_tenant_input({"tasks": {"enabled": True, "web": None}}) == {"categories": {"tasks": {"enabled": True}}}
    with pytest.raises(ValueError):
        validate_tenant_input({"unknown": {}})
