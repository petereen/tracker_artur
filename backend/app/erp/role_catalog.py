"""What a custom role can grant (Settings → Хэрэглэгч ба эрх → Үүрэг ба эрх).

A role combines

* **platform roles** (``system_roles``): the built-in access levels the whole
  workspace checks — member, team lead, manager, HR, legal counsel, auditor,
  contractor. ``admin`` is never granted through a role; it stays an explicit
  account role;
* **module permissions** (``capabilities``): resource × action pairs that
  the module APIs enforce through ``require_capability``.

Only permissions the code actually checks are offered, grouped by module, so
a role built here always does what the screen says.
"""
from __future__ import annotations

from app.core.roles import SYSTEM_ROLES

GRANTABLE_SYSTEM_ROLES: tuple[tuple[str, str, str], ...] = (
    ("member", "Ажилтан", "Өөрийн даалгавар, тайлан, ажлын цаг, чат, календарь."),
    ("team_lead", "Багийн ахлагч", "Багийн даалгавар хуваарилах, багийн статистик харах."),
    ("manager", "Менежер", "Бүх даалгавар, тайлан батлах, статистик, ажилтны төлөв."),
    ("hr", "Хүний нөөц", "Ажилтан, хэлтэс, чөлөө, ажлын цагийн тайлан."),
    ("legal_counsel", "Хуульч", "Гэрээ хянах, гэрээний архив."),
    ("client_auditor", "Аудитор", "Аналитик, тайланг зөвхөн унших."),
    ("contractor", "Гэрээт гүйцэтгэгч", "Өөрт оноосон ажил дээр хязгаарлагдмал хандалт."),
)
GRANTABLE_SYSTEM_ROLE_KEYS = frozenset(key for key, _, _ in GRANTABLE_SYSTEM_ROLES)
assert GRANTABLE_SYSTEM_ROLE_KEYS < SYSTEM_ROLES and "admin" not in GRANTABLE_SYSTEM_ROLE_KEYS

ACTION_LABELS = {
    "view": "Харах", "view_salary": "Цалингийн дүн харах", "create": "Үүсгэх", "edit": "Засах",
    "archive": "Архивлах", "approve": "Батлах", "export": "Экспортлох", "calculate": "Тооцоолох",
    "pay": "Олгох", "submit": "Илгээх", "cancel": "Цуцлах", "post": "Бүртгэлд тусгах", "administer": "Удирдах",
}

# (module key, label, licensed feature or None, ((resource, label, actions), ...))
MODULES: tuple[tuple[str, str, str | None, tuple[tuple[str, str, tuple[str, ...]], ...]], ...] = (
    ("crm", "CRM", "crm", (
        ("parties", "Харилцагч", ("view", "create", "edit", "archive")),
        ("crm_activity", "Харилцаа холбоо, ажил", ("view", "create", "edit", "archive")),
        ("crm_settings", "CRM тохиргоо", ("view", "edit")),
    )),
    ("budget", "Төсөв, гүйцэтгэл", "budget", (
        ("budget", "Төсөв", ("view", "create", "edit", "approve", "archive", "export")),
        ("budget_settings", "Төсвийн данс ба тохиргоо", ("view", "create", "edit", "archive")),
    )),
    ("payroll", "Цалин", "payroll", (
        ("payroll", "Цалин бодолт", ("view", "view_salary", "create", "calculate", "approve", "pay", "export", "administer")),
    )),
    ("accounting", "Нягтлан бодох бүртгэл", None, (
        ("accounts", "Дансны төлөвлөгөө", ("view", "create", "edit", "administer")),
        ("journal_entry", "Ерөнхий журналын бичилт", ("view", "create", "edit", "submit", "approve", "post", "cancel")),
        ("payment_entry", "Төлбөрийн бичилт", ("view", "create", "edit", "submit", "approve", "post", "cancel")),
    )),
    ("erp_admin", "ERP удирдлага", None, (
        ("erp_dashboard", "ERP хяналтын самбар", ("view",)),
        ("erp_settings", "ERP тохиргоо", ("administer",)),
        ("erp_roles", "Үүрэг ба эрх удирдах", ("administer",)),
        ("erp_custom_fields", "Нэмэлт талбар", ("administer",)),
        ("erp_imports", "Өгөгдөл импорт", ("administer",)),
        ("erp_approval_rules", "Батлах дүрэм", ("administer",)),
    )),
)
CATALOG_PAIRS = frozenset((resource, action) for _, _, _, resources in MODULES for resource, _, actions in resources for action in actions)


def catalog(licensed: set[str] | None = None) -> dict:
    """The role editor's catalog; modules outside the license are omitted."""
    return {
        "system_roles": [{"key": key, "label": label, "description": description} for key, label, description in GRANTABLE_SYSTEM_ROLES],
        "modules": [
            {
                "key": key, "label": label,
                "resources": [
                    {"key": resource, "label": resource_label, "actions": [{"key": action, "label": ACTION_LABELS.get(action, action)} for action in actions]}
                    for resource, resource_label, actions in resources
                ],
            }
            for key, label, feature, resources in MODULES
            if feature is None or licensed is None or feature in licensed
        ],
        "action_labels": ACTION_LABELS,
    }


def normalize_system_roles(values) -> list[str]:
    roles = sorted({str(value) for value in values or []})
    unknown = [role for role in roles if role not in GRANTABLE_SYSTEM_ROLE_KEYS]
    if unknown:
        raise ValueError(f"erp_role_system_role_not_grantable:{unknown[0]}")
    return roles


def granted_system_roles(values) -> set[str]:
    """Platform roles a stored role grants (unknown/admin entries ignored)."""
    return {str(value) for value in (values or []) if str(value) in GRANTABLE_SYSTEM_ROLE_KEYS}
