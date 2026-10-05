"""Notification categories, tenant-wide rules and personal preferences.

Every notification ``kind`` belongs to one category. Two layers decide where
a notification goes:

* the tenant (Settings → Автоматжуулалт ба интеграци → «Мэдэгдлийн тохиргоо»,
  ``organization.settings["notifications"]``): a category can be switched off
  for everyone, its web and Telegram defaults set, and personal changes
  allowed or locked;
* the user (Profile → «Мэдэгдлийн тохиргоо»,
  ``user_accounts.preferences["notifications"]``): web / Telegram per
  category, only where the tenant allows changes.

Telegram delivery follows exactly the same resolution as the in-app bell:
``create_notifications`` and the outbox drain ask ``resolve`` before a
message is queued or sent, and the bot's scheduled prompts ask
``delivery_for_employee_sync`` before sending.

The legacy daily check-in questionnaire (``checkin``) is off by default and
only exists for the primary tenant (the ``legacy_workspace`` feature).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

TENANT_KEY = "notifications"
USER_KEY = "notifications"
CHANNELS = ("web", "telegram")


@dataclass(frozen=True, slots=True)
class Category:
    key: str
    label: str
    description: str
    kinds: frozenset[str]
    prefixes: tuple[str, ...] = ()
    default_enabled: bool = True
    default_web: bool = True
    default_telegram: bool = True
    # Only the primary tenant has the legacy check-in tools.
    legacy: bool = False


CATEGORIES: tuple[Category, ...] = (
    Category("tasks", "Даалгавар", "Шинэ даалгавар, хянах хүсэлт, хугацааны сануулга, хугацаа хэтэрсэн.",
             frozenset({"task_assigned", "task_review_requested", "task_collaboration_updated", "task_deadline", "task_overdue", "task"}), ("task_",)),
    Category("reports", "Тайлан", "Өдөр, 7 хоног, сар, улирал, хагас жил, жилийн тайлангийн сануулга ба илгээсэн тайлан.",
             frozenset({"daily_report", "daily_reminder", "monthly_report", "periodic_report", "report_submitted"}), ("report_",)),
    Category("worktime", "Ажлын цаг", "Ажлын цагаа эхлүүлэх, дуусгахыг сануулах.",
             frozenset({"worktime_reminder"}), ("worktime_",)),
    Category("calendar", "Календарь ба төсөл", "Уулзалт, үйл явдал, төслийн гишүүнчлэл ба хугацаа, компанийн төлөвлөгөө.",
             frozenset({"calendar_reminder", "event", "company_plan_created"}), ("project_", "calendar_", "company_plan")),
    Category("contracts", "Гэрээ", "Гэрээ хянах, батлах, гарын үсэг, хугацаа дуусах.",
             frozenset(), ("contract_",)),
    Category("hr", "Хүний нөөц", "Чөлөөний хүсэлт, шийдвэр, төрсөн өдрийн мэндчилгээ.",
             frozenset({"birthday"}), ("hr_", "leave_")),
    Category("crm", "CRM", "Харилцагчийн ажил оноох, хугацаа ба хэтэрсэн сануулга.",
             frozenset(), ("crm_",)),
    Category("payroll", "Цалин", "Цалингийн батлалт, олголт, хуудас.",
             frozenset({"earning", "bank_payout", "cash_vouchers"}), ("payroll_",)),
    Category("digests", "Өдрийн тойм", "Өглөө, оройн даалгаврын тойм ба удирдлагын багийн тойм.",
             frozenset({"task_digest", "manager_digest", "report_digest"}), ("digest_",)),
    Category("checkin", "Өдрийн check-in асуулга (хуучин)", "Хуучин Telegram асуулга, бөглөөгүй ажилтны сэрэмжлүүлэг ба хураангуй.",
             frozenset({"daily_checkin", "checkin_missed", "checkin_summary"}), ("checkin_",),
             default_enabled=False, default_web=False, default_telegram=False, legacy=True),
    Category("system", "Бусад", "Бусад системийн мэдэгдэл.", frozenset()),
)
CATEGORY_BY_KEY = {category.key: category for category in CATEGORIES}
_KIND_INDEX = {kind: category.key for category in CATEGORIES for kind in category.kinds}


def category_for(kind: str | None) -> str:
    kind = kind or ""
    if kind in _KIND_INDEX:
        return _KIND_INDEX[kind]
    for category in CATEGORIES:
        if any(kind.startswith(prefix) for prefix in category.prefixes):
            return category.key
    return "system"


@dataclass(frozen=True, slots=True)
class Delivery:
    web: bool
    telegram: bool

    @property
    def any(self) -> bool:
        return self.web or self.telegram


def _bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def tenant_rules(organization_settings: dict | None, *, legacy_available: bool = True) -> dict[str, dict]:
    """Normalized tenant rules for every category."""
    raw = (organization_settings or {}).get(TENANT_KEY)
    raw = raw.get("categories") if isinstance(raw, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    rules: dict[str, dict] = {}
    for category in CATEGORIES:
        item = raw.get(category.key) if isinstance(raw.get(category.key), dict) else {}
        enabled = _bool(item.get("enabled"), category.default_enabled)
        if category.legacy and not legacy_available:
            enabled = False
        rules[category.key] = {
            "enabled": enabled,
            "web": _bool(item.get("web"), category.default_web),
            "telegram": _bool(item.get("telegram"), category.default_telegram),
            "user_editable": _bool(item.get("user_editable"), True),
        }
    return rules


def user_choices(preferences: dict | None) -> dict[str, dict]:
    raw = (preferences or {}).get(USER_KEY)
    raw = raw.get("categories") if isinstance(raw, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    choices: dict[str, dict] = {}
    for key, item in raw.items():
        if key in CATEGORY_BY_KEY and isinstance(item, dict):
            choice = {channel: item[channel] for channel in CHANNELS if isinstance(item.get(channel), bool)}
            if choice:
                choices[key] = choice
    return choices


def resolve_category(rules: dict[str, dict], choices: dict[str, dict], category: str) -> Delivery:
    rule = rules.get(category) or rules["system"]
    if not rule["enabled"]:
        return Delivery(False, False)
    web, telegram = rule["web"], rule["telegram"]
    if rule["user_editable"]:
        choice = choices.get(category, {})
        web = choice.get("web", web)
        telegram = choice.get("telegram", telegram)
    return Delivery(bool(web), bool(telegram))


def resolve(organization_settings: dict | None, preferences: dict | None, kind: str, *, legacy_available: bool = True) -> Delivery:
    """Where a notification of ``kind`` goes for one recipient."""
    return resolve_category(tenant_rules(organization_settings, legacy_available=legacy_available), user_choices(preferences), category_for(kind))


def validate_tenant_input(categories: dict[str, dict]) -> dict:
    unknown = set(categories) - set(CATEGORY_BY_KEY)
    if unknown:
        raise ValueError(f"unknown_category:{sorted(unknown)[0]}")
    normalized = {}
    for key, item in categories.items():
        normalized[key] = {field: bool(item[field]) for field in ("enabled", "web", "telegram", "user_editable") if field in item and item[field] is not None}
    return {"categories": normalized}


def merge_user_choices(preferences: dict | None, rules: dict[str, dict], categories: dict[str, dict]) -> dict:
    """Store only choices the tenant lets the user make."""
    unknown = set(categories) - set(CATEGORY_BY_KEY)
    if unknown:
        raise ValueError(f"unknown_category:{sorted(unknown)[0]}")
    choices = user_choices(preferences)
    for key, item in categories.items():
        rule = rules[key]
        if not rule["enabled"] or not rule["user_editable"]:
            continue
        choice = {channel: bool(item[channel]) for channel in CHANNELS if item.get(channel) is not None}
        if choice:
            choices[key] = {**choices.get(key, {}), **choice}
    return {**(preferences or {}), USER_KEY: {"categories": choices}}


# ── Synchronous lookups for the bot (scheduler, outbox drain) ──────────────

def _legacy_available_sync(session, organization_id: int | None) -> bool:
    from app.models.models import Organization

    if organization_id is None:
        return True
    organization = session.get(Organization, organization_id)
    return bool(organization and getattr(organization, "is_primary", False))


def delivery_for_employee_sync(employee_id: int, kind: str) -> Delivery:
    """Resolution for a worker (and their account, if they have one).

    A failed lookup falls back to the category defaults: preferences decide
    where a message goes, they are not an access boundary.
    """
    try:
        return _delivery_for_employee_sync(employee_id, kind)
    except Exception:  # noqa: BLE001
        log.warning("notification_preferences.lookup_failed employee=%s kind=%s", employee_id, kind, exc_info=True)
        return resolve(None, None, kind)


def _delivery_for_employee_sync(employee_id: int, kind: str) -> Delivery:
    from sqlalchemy import select

    from app.bot.db import get_session
    from app.models.models import Employee, Organization, UserAccount

    with get_session() as session:
        employee = session.get(Employee, employee_id)
        if employee is None:
            return Delivery(False, False)
        organization = session.get(Organization, employee.organization_id) if employee.organization_id else None
        account = session.execute(
            select(UserAccount).where(UserAccount.employee_id == employee.id, UserAccount.status == "active")
        ).scalars().first()
        return resolve(
            organization.settings if organization else None,
            account.preferences if account else None,
            kind,
            legacy_available=_legacy_available_sync(session, employee.organization_id),
        )


def telegram_allowed_sync(recipient_tg: str | None, kind: str, organization_id: int | None = None) -> bool:
    """Whether a queued Telegram message may still go out (outbox drain)."""
    if not recipient_tg:
        return False
    try:
        return _telegram_allowed_sync(recipient_tg, kind, organization_id)
    except Exception:  # noqa: BLE001
        log.warning("notification_preferences.lookup_failed recipient=%s kind=%s", recipient_tg, kind, exc_info=True)
        return resolve(None, None, kind).telegram


def _telegram_allowed_sync(recipient_tg: str, kind: str, organization_id: int | None) -> bool:
    from sqlalchemy import select

    from app.bot.db import get_session
    from app.models.models import Employee, Organization, UserAccount

    with get_session() as session:
        query = select(Employee).where(Employee.telegram_id == str(recipient_tg))
        if organization_id is not None:
            query = query.where(Employee.organization_id == organization_id)
        employee = session.execute(query).scalars().first()
        tenant_id = employee.organization_id if employee else organization_id
        organization = session.get(Organization, tenant_id) if tenant_id else None
        account = None
        if employee is not None:
            account = session.execute(
                select(UserAccount).where(UserAccount.employee_id == employee.id, UserAccount.status == "active")
            ).scalars().first()
        return resolve(
            organization.settings if organization else None,
            account.preferences if account else None,
            kind,
            legacy_available=_legacy_available_sync(session, tenant_id),
        ).telegram


def tenant_category_enabled_sync(organization_id: int | None, category: str) -> bool:
    """Tenant switch alone (manager alerts and summaries have no personal layer)."""
    from app.bot.db import get_session
    from app.models.models import Organization

    try:
        with get_session() as session:
            organization = session.get(Organization, organization_id) if organization_id else None
            rules = tenant_rules(organization.settings if organization else None, legacy_available=_legacy_available_sync(session, organization_id))
    except Exception:  # noqa: BLE001
        log.warning("notification_preferences.lookup_failed tenant=%s category=%s", organization_id, category, exc_info=True)
        rules = tenant_rules(None)
    rule = rules.get(category) or rules["system"]
    return bool(rule["enabled"] and rule["telegram"])
