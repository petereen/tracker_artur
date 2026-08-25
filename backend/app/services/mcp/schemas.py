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
    employee_reference: str | None = Field(default=None, max_length=4096)
    project_reference: str | None = Field(default=None, max_length=4096)
    date_from: date | None = None
    date_to: date | None = None


class ProjectsSearchInput(StrictInput):
    entity: Literal["projects", "plans", "milestones"] = "projects"
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
    reviewer: str | None = Field(default=None, max_length=200)
    priority: Literal[1, 2, 3] = 2
    deadline_at: datetime | None = None
    project_ref: str | None = Field(default=None, max_length=200)


class TaskPrepareUpdateInput(StrictInput):
    task_reference: str = Field(min_length=16, max_length=4096)
    workflow_status: Literal["backlog", "to_do", "in_progress", "review", "done", "cancelled"] | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    start_at: datetime | None = None
    deadline_at: datetime | None = None
