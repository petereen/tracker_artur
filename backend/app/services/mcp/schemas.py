"""Strict, stable MCP input schemas. Physical database fields never leak here."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeSearchInput(StrictInput):
    query: str = Field(min_length=1, max_length=500)
    search_mode: Literal["hybrid", "semantic", "keyword"] = "hybrid"
    file_types: list[str] = Field(default_factory=list, max_length=10)
    limit: int = Field(default=5, ge=1, le=5)
    delivery: Literal["none", "attachment", "link"] = "none"

    @field_validator("query")
    @classmethod
    def trim_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value


class KnowledgeFetchInput(StrictInput):
    reference: str = Field(min_length=16, max_length=4096)


class RecordsSearchInput(StrictInput):
    entity: Literal["employees"] = "employees"
    query: str | None = Field(default=None, max_length=200)
    include_inactive: bool = False
    limit: int = Field(default=10, ge=1, le=50)


class RecordsGetInput(StrictInput):
    reference: str = Field(min_length=16, max_length=4096)


class RecordsAggregateInput(StrictInput):
    entity: Literal["employees"] = "employees"
    group_by: Literal["active_status", "job_title"] = "active_status"


class TasksSearchInput(StrictInput):
    completion_state: Literal["open", "completed", "all"] = "open"
    workflow_status: str | None = Field(default=None, max_length=32)
    blockers_only: bool = False
    active_only: bool = False
    limit: int = Field(default=10, ge=1, le=50)
    employee_reference: str | None = Field(default=None, max_length=4096, description="Opaque reference of the employee whose tasks to retrieve. For the caller's own tasks, use the `employee_reference` from the grounding context's `current_employee`. Omit only to search the whole permitted scope.")
    project_reference: str | None = Field(default=None, max_length=4096)
    date_from: date | None = None
    date_to: date | None = None


class ProjectsSearchInput(StrictInput):
    entity: Literal["projects", "plans", "milestones", "ideas"] = Field(default="projects", description="plans = approved company plan items; ideas = employee plan ideas/suggestions.")
    completion_state: Literal["open", "completed", "all"] = "open"
    active_only: bool = False
    limit: int = Field(default=10, ge=1, le=50)
    employee_reference: str | None = Field(default=None, max_length=4096)
    project_reference: str | None = Field(default=None, max_length=4096)
    date_from: date | None = None
    date_to: date | None = None


class CalendarAvailabilityInput(StrictInput):
    intent: Literal["events", "schedule", "availability"] = "availability"
    timeframe: Literal["today", "this_week", "custom"] = "today"
    date_from: date | None = None
    date_to: date | None = None
    scope: Literal["self", "team", "organization"] = "self"
    employee_reference: str | None = Field(default=None, max_length=4096)
    timezone_name: str | None = Field(default=None, max_length=64)


class StatsGetInput(StrictInput):
    metrics: list[str] = Field(default_factory=lambda: ["task_completion"], min_length=1, max_length=8)
    timeframe: Literal["today", "this_week", "this_month", "custom"] = "this_week"
    date_from: date | None = None
    date_to: date | None = None
    employee_reference: str | None = Field(default=None, max_length=4096)
    project_reference: str | None = Field(default=None, max_length=4096)
    compare_previous: bool = False
    presentation: Literal["summary", "table"] = "summary"


class ERPReadInput(StrictInput):
    resource: Literal["dashboard", "documents"] = "dashboard"
    document_type: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=10, ge=1, le=25)


class ExchangeRateInput(StrictInput):
    provider: str = Field(min_length=1, max_length=100)
    pair: str = Field(min_length=1, max_length=500)
    force_refresh: StrictBool = False
    request_type: Literal["single", "all", "calculated"] = "single"

    @field_validator("provider", "pair")
    @classmethod
    def non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class TaskPrepareCreateInput(StrictInput):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=6000)
    assignee: str | None = Field(default=None, max_length=200)
    participants: list[str] | None = Field(default=None, max_length=50, description="Every explicitly named task participant; use employee names or @usernames.")
    reviewer: str | None = Field(default=None, max_length=200)
    priority: Literal[1, 2, 3] = 2
    start_at: datetime | None = None
    deadline_at: datetime | None = None
    project_ref: str | None = Field(default=None, max_length=200)


class TaskPrepareUpdateInput(StrictInput):
    task_reference: str = Field(min_length=16, max_length=4096)
    workflow_status: Literal["backlog", "to_do", "in_progress", "review", "done", "cancelled"] | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    start_at: datetime | None = None
    deadline_at: datetime | None = None


EMPLOYEE_REFERENCE_HELP = "Opaque employee reference (from current_employee or oyuns_records_search). Null means the caller's permitted scope."


class ReportsSearchInput(StrictInput):
    report_types: list[Literal["daily", "monthly", "next_month_plan"]] = Field(default_factory=lambda: ["daily", "monthly"], min_length=1, max_length=3)
    employee_reference: str | None = Field(default=None, max_length=4096, description=EMPLOYEE_REFERENCE_HELP)
    date_from: date | None = Field(default=None, description="Report period start (inclusive). Defaults to 7 days ago.")
    date_to: date | None = Field(default=None, description="Report period end (inclusive). Defaults to today.")
    status: Literal["any", "submitted", "approved", "missing"] = Field(default="any", description="missing = not yet submitted (awaiting/draft).")
    text_query: str | None = Field(default=None, max_length=200, description="Words that must appear in the report text.")
    include_text: bool = Field(default=True, description="Include report text excerpts.")
    limit: int = Field(default=10, ge=1, le=30)


class WorktimeGetInput(StrictInput):
    view: Literal["status_now", "totals", "daily"] = Field(default="totals", description="status_now = who is working/on break right now; totals = hours per employee; daily = per-day clock in/out.")
    scope: Literal["self", "team"] = Field(default="self", description="team = everyone the caller may see (managers, HR, team leads).")
    employee_reference: str | None = Field(default=None, max_length=4096, description=EMPLOYEE_REFERENCE_HELP)
    date_from: date | None = Field(default=None, description="Defaults to today.")
    date_to: date | None = Field(default=None, description="Defaults to date_from.")


class HRGetInput(StrictInput):
    resource: Literal["departments", "leave_requests", "leave_balances", "attendance"]
    employee_reference: str | None = Field(default=None, max_length=4096, description=EMPLOYEE_REFERENCE_HELP)
    year: int | None = Field(default=None, ge=2000, le=2100)
    leave_status: Literal["pending", "approved", "rejected", "cancelled"] | None = None
    date_from: date | None = Field(default=None, description="Attendance range start; max 31 days. Defaults to this month.")
    date_to: date | None = None


class CRMSearchInput(StrictInput):
    resource: Literal["summary", "parties", "activities"] = Field(default="summary", description="summary = open/overdue/pipeline counts; parties = clients/partners; activities = CRM interactions and follow-ups.")
    query: str | None = Field(default=None, max_length=160)
    party_kind: Literal["all", "customer", "supplier", "prospect"] = "all"
    state: Literal["open", "closed", "all"] = "open"
    overdue_only: bool = False
    mine_only: bool = False
    limit: int = Field(default=10, ge=1, le=50)


class ContractsSearchInput(StrictInput):
    query: str | None = Field(default=None, max_length=200)
    status: Literal["DRAFT", "PENDING_REVIEW", "CHANGES_REQUESTED", "APPROVED", "REJECTED", "SIGNED_AND_STAMPED"] | None = None
    expiring_within_days: int | None = Field(default=None, ge=1, le=366, description="Only contracts whose end date falls within this many days from today.")
    limit: int = Field(default=10, ge=1, le=30)


class PayrollSummaryInput(StrictInput):
    view: Literal["months", "totals", "per_employee"] = Field(default="totals", description="months = list payroll months and run status; totals = company totals for a month; per_employee = gross/net per employee.")
    month: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$", description="YYYY-MM. Defaults to the latest payroll month.")
    employee_reference: str | None = Field(default=None, max_length=4096, description=EMPLOYEE_REFERENCE_HELP)
