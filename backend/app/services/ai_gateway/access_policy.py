"""Organization-wide access rights of the OYUNS AI assistant.

Admins choose, per data section, whether the assistant may read it and
whether it may prepare changes (confirmation previews). The policy only
narrows access: every tool call still runs with the asking user's own roles
and page scopes.

Stored in ``organization.settings["ai_agent"]["access"]`` as
``{section: {"read": bool, "write": bool}}``. A section missing from the
stored policy is allowed, so an organization that never configured it keeps
full access.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ACCESS_KEY = "access"


@dataclass(frozen=True, slots=True)
class AccessSection:
    key: str
    group: str
    label: str
    description: str
    read_tools: tuple[str, ...]
    write_tools: tuple[str, ...] = ()


GROUPS: tuple[tuple[str, str], ...] = (
    ("work", "Ажил ба төлөвлөлт"),
    ("people", "Хүний нөөц"),
    ("business", "Борлуулалт ба санхүү"),
    ("knowledge", "Мэдлэг"),
)

SECTIONS: tuple[AccessSection, ...] = (
    AccessSection("tasks", "work", "Даалгавар", "Даалгавар хайх; үүсгэх/засах ноорог бэлтгэх (хэрэглэгч баталгаажуулна)", ("oyuns_tasks_search",), ("oyuns_tasks_prepare_create", "oyuns_tasks_prepare_update")),
    AccessSection("projects", "work", "Төсөл ба төлөвлөгөө", "Төсөл, компанийн төлөвлөгөө, санаа", ("oyuns_projects_search",)),
    AccessSection("calendar", "work", "Календарь", "Завтай/завгүй цаг", ("oyuns_calendar_availability",)),
    AccessSection("reports", "work", "Ажлын тайлан", "Өдөр, сар, үечилсэн тайлан ба төлөвлөгөө", ("oyuns_reports_search",)),
    AccessSection("directory", "people", "Ажилтны лавлах", "Ажилтны жагсаалт, албан тушаал, нэгтгэл", ("oyuns_records_search", "oyuns_records_get", "oyuns_records_aggregate")),
    AccessSection("worktime", "people", "Ажлын цаг ба ирц", "Цаг бүртгэл, ажиллаж буй хүмүүс, ажилласан цаг", ("oyuns_worktime_get",)),
    AccessSection("hr", "people", "Чөлөө ба хэлтэс", "Хэлтэс, чөлөөний хүсэлт, үлдэгдэл, сарын ирц", ("oyuns_hr_get",)),
    AccessSection("payroll", "people", "Цалин", "Сарын цалингийн нэгтгэл (зөвхөн admin/HR)", ("oyuns_payroll_summary",)),
    AccessSection("crm", "business", "CRM", "Харилцагч, түнш, харилцааны түүх", ("oyuns_crm_search",)),
    AccessSection("contracts", "business", "Гэрээ", "Гэрээ, албан бичиг, хугацаа", ("oyuns_contracts_search",)),
    AccessSection("erp", "business", "ERP баримт", "ERP самбарын дүн ба баримтууд", ("oyuns_erp_read",)),
    AccessSection("analytics", "business", "Статистик ба KPI", "Гүйцэтгэлийн үзүүлэлтүүд", ("oyuns_stats_get",)),
    AccessSection("exchange", "business", "Валютын ханш", "Монголбанкны ханш", ("oyuns_exchange_rate_get",)),
    AccessSection("knowledge", "knowledge", "Компанийн мэдлэг ба файл", "Дотоод журам, баримт бичиг, файлууд", ("oyuns_knowledge_search", "oyuns_knowledge_fetch")),
)

_SECTIONS_BY_KEY = {section.key: section for section in SECTIONS}


def normalize(raw: Any) -> dict[str, dict[str, bool]]:
    """Return the full matrix; missing entries are allowed, writes need reads."""
    raw = raw if isinstance(raw, dict) else {}
    matrix: dict[str, dict[str, bool]] = {}
    for section in SECTIONS:
        entry = raw.get(section.key)
        entry = entry if isinstance(entry, dict) else {}
        read = bool(entry.get("read", True))
        write = bool(section.write_tools) and read and bool(entry.get("write", True))
        matrix[section.key] = {"read": read, "write": write}
    return matrix


@dataclass(frozen=True, slots=True)
class AccessPolicy:
    denied_tools: frozenset[str] = frozenset()

    def allows(self, tool_name: str) -> bool:
        return tool_name not in self.denied_tools

    def can_read(self, section_key: str) -> bool:
        section = _SECTIONS_BY_KEY[section_key]
        return any(self.allows(tool) for tool in section.read_tools)


FULL_ACCESS = AccessPolicy()


def policy_from_matrix(matrix: dict[str, dict[str, bool]]) -> AccessPolicy:
    denied: set[str] = set()
    for section in SECTIONS:
        entry = matrix.get(section.key, {})
        if not entry.get("read", True):
            denied.update(section.read_tools)
        if not entry.get("write", True):
            denied.update(section.write_tools)
    return AccessPolicy(frozenset(denied)) if denied else FULL_ACCESS


def policy_from_config(stored: dict) -> AccessPolicy:
    return policy_from_matrix(normalize(stored.get(ACCESS_KEY)))


def catalog() -> list[dict]:
    """Groups and sections for the settings UI."""
    return [
        {
            "key": key,
            "label": label,
            "sections": [
                {"key": section.key, "label": section.label, "description": section.description, "has_write": bool(section.write_tools)}
                for section in SECTIONS if section.group == key
            ],
        }
        for key, label in GROUPS
    ]
