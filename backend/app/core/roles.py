"""Canonical enterprise role names and feature-specific role groups."""

SYSTEM_ROLES = frozenset({
    "admin",
    "manager",
    "team_lead",
    "hr",
    "member",
    "contractor",
    "client_auditor",
})

WORKTIME_REPORT_ROLES = frozenset({"admin", "manager", "hr", "team_lead"})

