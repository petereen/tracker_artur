"""Canonical enterprise role names and feature-specific role groups."""

SYSTEM_ROLES = frozenset({
    "admin",
    "manager",
    "team_lead",
    "hr",
    "member",
    "contractor",
    "client_auditor",
    "legal_counsel",
})

WORKTIME_REPORT_ROLES = frozenset({"admin", "manager", "hr", "team_lead"})
# Roles that see the whole tenant in the Telegram companion (same as the web
# workspace: a team lead keeps the personal scope).
TELEGRAM_MANAGEMENT_ROLES = frozenset({"admin", "manager"})
