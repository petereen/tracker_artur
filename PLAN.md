Plan
Enterprise PM & Internal PSA Evolution Plan
Summary
Evolve tracker_artur incrementally into a single-company enterprise PM/PSA platform while preserving its Telegram-first workflows, existing PostgreSQL data, OYUNS AI, work reports, and time tracking.

The target architecture will use:

FastAPI + PostgreSQL as the shared domain core.
Versioned REST APIs for commands and queries.
WebSockets backed by durable PostgreSQL domain events for live updates.
React/Vite with role-adaptive desktop, responsive web, and Telegram Mini App views.
Email/password employee accounts linked to existing Telegram identities.
Internal PSA capabilities: clients, projects, budgets, rates, billable time, utilization, and currency conversion. Invoicing is excluded.
PostgreSQL-backed jobs and transactional outboxes; no Redis requirement for the initial single-company deployment.
Success targets:

User feedback within 100 ms through optimistic UI.
Normal API reads under 300 ms p95 and writes under 500 ms p95.
Cross-channel changes visible within 2 seconds p95.
Drag interactions sustain approximately 60 fps on standard business hardware.
WCAG 2.2 AA keyboard, contrast, screen-reader, and reduced-motion compliance.
No duplicate active timers, lost task changes, unauthorized data access, or duplicate Telegram notifications.
1. Database Schema Expansion
Conventions and migration strategy
Retain existing integer primary keys and add public_id UUID UNIQUE where externally shareable identifiers are needed.
Store timestamps as TIMESTAMPTZ in UTC and retain timezone or local_work_date for local-day behavior.
Add organization_id to enterprise entities, pointing to a singleton organizations row. Backfill it before making it non-null.
Use additive expand-and-contract migrations. Keep legacy tables, routes, and status aliases available for two releases.
Add version INTEGER NOT NULL DEFAULT 1 and updated_at to mutable collaborative records for optimistic concurrency.
All destructive and security-relevant mutations write an audit log and domain event in the same transaction.
Identity, organization, and RBAC
organizations: id, public_id, name, timezone, base_currency CHAR(3), settings JSONB, timestamps. Default timezone Asia/Ulaanbaatar; base currency MNT.
user_accounts: id, nullable unique employee_id, unique case-insensitive email, password_hash, status, locale, must_change_password, failed_login_count, locked_until, last_login_at, timestamps.
Migrate admin_users into this table.
Hash new passwords with Argon2id; verify and transparently upgrade existing bcrypt hashes.
refresh_sessions: account, hashed refresh token, device label, expiry, revocation, last-used time. Index active sessions by account and expiry.
role_assignments: user_id, role, optional team_id, project_id, or client_id, validity dates.
Roles: admin, manager, team_lead, member, contractor, client_auditor.
Unique index across user, role, and scope.
Extend employees with unique nullable email, manager_id self-reference, job title, primary language, employment type, weekly capacity minutes, metadata, and timestamps.
Existing employees without email retain Telegram access until an administrator invites them to web access.
A user account and Telegram identity always resolve to the same employee.
Teams and resource planning
teams: organization, name, code, parent team, manager, timezone, active flag. Unique organization/code index.
team_members: team, employee, team role, allocation percentage, membership dates. Unique active team/employee membership.
skills and employee_skills: normalized skill name, proficiency, verification state, and last-used date.
shift_schedules: employee/team, weekday, local start/end, break allowance, timezone, effective dates.
time_off: employee, type, local start/end dates, partial-day minutes, approval status, approver.
resource_allocations: employee, project, date range, planned minutes or percentage, source, status.
Capacity calculation:
Available capacity = scheduled minutes − approved time off.
Planned load = project allocations plus estimated task work.
Over-allocation warning begins above 100%; configurable warning begins at 90%.
Clients, projects, budgets, and rates
clients: organization, public ID, code, name, status, default currency, contacts metadata. Unique organization/code index.
projects: organization, client, public ID, code, name, description, status, manager, start/end dates, budget minutes, budget amount, currency, default billable flag, version, timestamps.
Statuses: draft, planned, active, on_hold, completed, cancelled.
Index by organization/status, client/status, manager/status, and date range.
project_members: project, employee, project role, allocation, billable flag, effective dates.
project_rates: project, optional employee or role, hourly amount, currency, effective dates. Prevent overlapping active rates for the same scope.
exchange_rate_snapshots: provider, base/quote currency, rate, fetched time, source payload hash.
Budget conversions persist the selected snapshot so historical totals do not change.
Budget burn uses approved billable time and rate snapshots. Invoice, tax, payment, and accounting-export entities are explicitly excluded.
Tasks, subtasks, dependencies, and views
Extend tasks with:

organization_id, nullable project_id, nullable parent_task_id, public ID.
Title, markdown description, status, priority, primary owner, creator.
Start date, deadline, estimate minutes, sort position, completion information.
version, archived flag, timestamps.
Statuses: backlog, to_do, in_progress, review, done, cancelled.
Migration mapping:
open → to_do
in_progress → in_progress
done → done
cancelled → cancelled
overdue → to_do; overdue thereafter becomes a computed deadline condition rather than a workflow status.
Indexes: project/status/position, primary owner/status/deadline, parent/position, organization/deadline, and active overdue candidates.
Supporting entities:

Subtasks use the same tasks table through parent_task_id.
task_assignees: task, employee, assignment role, assigned time. Enforce one primary owner while allowing multiple contributors.
task_dependencies: predecessor, successor, dependency type. Unique pair; service validation rejects self-links and cycles.
task_check_items: task, text, completion state, assignee, position, timestamps.
task_comments: retain existing rows; add author account, edited time, resolved state, and mentions.
attachments: organization, object type/ID, storage key, filename, MIME type, size, checksum, uploader, scan state.
saved_views: user, module, view type, filters, grouping, visible columns, sort, sharing state.
Every drag persists destination status/swimlane and fractional sort position atomically.
Time entries and punch clock
Expand work_time_entries into the canonical time_entries model:

Employee, optional project/task/report, local work date, timezone.
Entry type: work or break.
Work mode: in_person or remote; null for breaks.
Start/end timestamps, source channel, notes.
Billable flag, approval state, approver, rate/currency snapshot.
Version and timestamps.
Partial unique index allowing only one open interval per employee.
PostgreSQL range/exclusion protection against overlapping intervals.
Indexes by employee/local date, project/date, task/date, approval state, and open timer.
Migrate existing intervals with their report date and original mode.
Clock behavior:

Starting Office or Remote closes any incompatible open interval and opens one canonical work entry.
Starting lunch closes work and opens a break; ending lunch closes the break and resumes the previous work mode.
/daystart, /dayend, /remotestart, /remoteend, /worktime, web controls, and Mini App controls call the same service.
Intervals crossing a local midnight are split safely when closed.
Utilization = productive work minutes ÷ available capacity.
Billable ratio = approved billable work minutes ÷ productive work minutes.
Check-ins and reports
Preserve existing questions, survey sessions, work reports, revisions, and Telegram prompts while extending them.

checkin_templates: organization/team, name, cadence, active flag.
checkin_questions: template, localized prompt, answer type, choices, required flag, position.
checkins: employee, template, local date, status, source, started/submitted timestamps.
checkin_answers: check-in, question, text/numeric/JSON value, timestamps.
Statuses: scheduled, in_progress, submitted, missed.
Unique employee/template/local-date index.
Extend work_reports with title, markdown content state, submitter, reviewer, submitted/reviewed timestamps, version, and approval metadata.

Workflow: draft → submitted → revision_requested → submitted → approved.
Map existing awaiting, draft, editing, and approved records without losing revisions.
report_revisions: immutable markdown snapshots with author and status.
report_comments: report/revision, reviewer, inline range metadata, text, resolution state.
Attachments use the shared attachment model.
Batch approval records one audit entry and individual report events.
OKRs, milestones, and corporate plans
objectives: organization, parent objective, owner team/employee, level, title, description, period, status, progress method, version.
key_results: objective, owner, metric type, start/target/current value, unit, confidence, due date, status.
milestones: organization/project, title, due date, status, owner, progress.
goal_links: objective/key result/milestone linked to a project, task, or report with contribution weight.
Index active objectives by period/level/owner and milestones by project/due date.
Migrate reusable company_plan_items into objectives or milestones while preserving source report references.
Audit, real-time, and background processing
audit_logs: actor account/employee, channel, action, entity type/ID, before/after JSON, request ID, IP/user agent, timestamp.
Append-only; redact passwords, tokens, voice payloads, and sensitive attachment contents.
Index entity timeline, actor timeline, action, and timestamp.
domain_events: monotonically increasing ID, organization, topic, aggregate type/ID, aggregate version, payload, timestamp.
Serves as the durable real-time cursor and integration source.
Extend notification_outbox with event ID, attempt count, last error, lease, and next-attempt time.
job_queue: job type, payload, state, run time, lease owner/expiry, attempts, deduplication key.
Workers claim jobs with FOR UPDATE SKIP LOCKED.
calendar_connections and calendar_event_links: encrypted OAuth credentials, scopes, sync cursor, task/event mapping, sync state, and last error.
2. API and Real-Time Engine
API contract
Use versioned REST under /api/v1; GraphQL and gRPC are not introduced because the existing clients and services are REST-based.

Core route groups:

/auth/login, /auth/refresh, /auth/logout, /auth/me, /auth/password, /auth/password-reset.
/employees, /teams, /skills, /time-off, /capacity.
/clients, /projects, /projects/{id}/members, /projects/{id}/rates.
/tasks, /tasks/{id}/assignees, /dependencies, /check-items, /comments, /attachments.
/time-entries, /clock/status, /clock/start, /clock/break, /clock/resume, /clock/stop.
/checkins, /checkin-templates.
/reports, /reports/{id}/submit, /request-revision, /approve, /reports/batch-approve.
/objectives, /key-results, /milestones, /analytics.
/assistant/drafts, /assistant/actions, /voice/transcriptions.
/integrations/google-calendar/connect, /callback, /sync, /disconnect.
Contract rules:

Cursor pagination for large lists; filter/sort/group fields remain explicit and validated.
Idempotency-Key on task creation, clock operations, approvals, and AI-draft confirmation.
ETag/If-Match uses record versions; conflicts return 409 with the latest record.
All permission checks use a server-built ActorContext; clients never submit trusted roles or scopes.
Old unversioned endpoints remain compatibility adapters during migration.
Authentication
Employee/admin login uses email and password.
Access tokens are short-lived and kept in memory.
Rotating refresh tokens use HttpOnly, Secure, SameSite=Lax cookies.
Password reset uses single-use hashed tokens delivered through an SMTP provider abstraction.
Telegram initData is exchanged for the same JWT claim shape used by web accounts.
Account, employee, Telegram identity, roles, teams, and permitted project/client scopes are resolved once per request.
Real-time protocol
WebSocket endpoint: /api/v1/realtime?cursor=<last_event_id>.
Event envelope: id, topic, entityType, entityId, version, operation, payload, occurredAt.
Topics include tasks, clocks, reports, check-ins, capacity, notifications, and OKRs.
PostgreSQL LISTEN/NOTIFY wakes API replicas; durable domain_events provides replay after reconnect or missed notifications.
Clients reconnect with exponential backoff and their last acknowledged cursor.
Nginx/ACA configuration must preserve WebSocket upgrade headers and idle connections.
Telegram/web synchronization
Move direct database writes out of Telegram handlers into shared application services.
Every mutation follows one transaction:
Authorize actor and validate invariant.
Lock/version-check the aggregate.
Save domain changes.
Save audit log, domain event, and required outbox records.
Commit once.
WebSocket clients update immediately from events.
Telegram delivery remains idempotent through the outbox and respects quiet hours.
Reconciliation jobs detect missed reminders, stale timers, failed calendar links, and unsent notifications.
3. Frontend Architecture and UX
Technology choices
Keep React 18, TypeScript, Vite, Tailwind, TanStack Query, Zustand, Recharts, and Sentry. Add:

React Router with real URL routes and permission-aware route guards.
dnd-kit for accessible Kanban drag-and-drop.
Motion for interruptible spring transitions and gesture feedback.
TanStack Table for virtualized enterprise lists.
React Markdown with GFM for report/task editing and preview.
Lucide icons and react-i18next.
Shared WebSocket/event-cache adapter for Query invalidation and optimistic reconciliation.
Component hierarchy
App
├─ AuthBoundary / ActorProvider / RealtimeProvider
├─ AppShell
│  ├─ AdaptiveSidebar
│  ├─ WorkspaceHeader
│  │  ├─ Breadcrumbs
│  │  ├─ GlobalSearch
│  │  ├─ QuickCreate
│  │  └─ NotificationCenter
│  └─ WorkspaceRouter
│     ├─ WorkerDashboard
│     │  ├─ PunchClock
│     │  ├─ DailyCheckinCards
│     │  ├─ PriorityTasks
│     │  └─ PersonalPerformance
│     ├─ ProjectsWorkspace
│     ├─ TaskWorkspace
│     │  ├─ ViewToolbar
│     │  ├─ KanbanBoard
│     │  ├─ TaskList
│     │  ├─ Timeline
│     │  ├─ Calendar
│     │  └─ TaskDetailSheet
│     ├─ ReportsAndApprovals
│     ├─ TeamCapacity
│     ├─ OKRsAndRoadmaps
│     └─ Administration
└─ DialogLayer / ToastLayer / CommandPalette
Mini App reuses worker dashboard, clock, task card, task sheet, and check-in components with a mobile navigation shell.

Productivity workflows
Global quick create supports keyboard shortcut, task templates, recent assignees, and AI/voice draft entry.
Kanban supports pointer and keyboard drag, swimlanes, inline title/owner/due-date editing, multi-select, undo, and optimistic rollback.
List, board, timeline, and calendar consume the same normalized query state and saved-view definition.
Task sheet presents overview, subtasks, dependencies, checklist, comments, files, time, and activity without forcing page navigation.
Manager approval center supports filters, side-by-side revisions, inline comments, bulk selection, and safe batch approval.
Capacity grid supports week/month ranges, workload heatmap, time-off overlay, and reassignment preview before commit.
Apple-style design system
Use system fonts with optical sizing; tighten large headings and preserve legible body leading.
Provide semantic light/dark tokens instead of a dark-only palette.
Apply translucent materials only to floating navigation, headers, popovers, and sheets; never stack translucent cards.
Use precise one-pixel borders, restrained shadows, and content-first surfaces.
Press feedback begins on pointer-down. Gesture-driven elements track 1:1 and remain interruptible.
Default motion uses critically damped springs around 0.3–0.4 seconds; bounce is reserved for momentum-driven drag release.
Task sheets enter and exit along the same anchored path.
prefers-reduced-motion, prefers-reduced-transparency, and prefers-contrast receive explicit alternatives.
Every drag/drop interaction has keyboard controls, visible focus, announcements, and non-drag fallback menus.
Desktop uses the full navigation shell; tablet collapses the sidebar; mobile and Mini App use bottom navigation and full-height sheets.
4. OYUNS, Voice, Calendar, and Financial Integrations
OYUNS action model
Extend the existing strict tool schemas with:

create_task_draft
update_task_draft
get_user_workload
search_company_knowledge
draft_report
summarize_team_reports
suggest_task_breakdown
suggest_reallocation
get_exchange_rate
prepare_calendar_event
Rules:

AI can propose drafts, summaries, and plans but cannot bypass RBAC or confirmation.
Permission filtering occurs before context reaches the model.
Tool results are validated with strict Pydantic schemas and additionalProperties: false.
Mutations require explicit confirmation and an idempotency key.
Prompts, model/version, latency, token usage, and safe failure category are observable; sensitive content is redacted.
Deterministic task, clock, knowledge, and report operations remain available when AI is unavailable.
Voice processing
Browser records audio with clear consent and duration/size limits.
API validates MIME type and stores only a short-lived encrypted object.
Mongolian audio goes to Chimege STT first; OpenAI transcription remains the configured fallback.
Normalized transcript is returned for user review.
OYUNS creates a task/report draft.
The user edits and confirms before any domain mutation.
Temporary audio is deleted after processing; transcript retention follows audit/privacy policy.
Long-running voice and AI work uses job_queue, progress events, retry limits, and cancellation.

Google Calendar
The current prefilled Google Calendar URL remains as fallback. True synchronization adds:

Per-user OAuth connection with encrypted refresh tokens and minimum scopes.
Task-to-event links and Google sync tokens.
Push webhook endpoint with signature/channel validation.
Idempotent outbound create/update/delete jobs.
Conflict rule: OYUNS task identity remains canonical; calendar changes update scheduling fields only when the user enabled bidirectional sync.
Deleted or revoked connections stop synchronization without deleting tasks.
Calendar failures show actionable state while leaving task operations available.
Exchange-rate usage
OYUNS performs live lookup through the existing rate service.
Project quotes persist provider, pair, fetched time, and rate snapshot.
Base financial reporting uses MNT while preserving source currency.
Stale or failed lookups are clearly labeled and never silently substituted.
5. Phase-by-Phase Execution Roadmap
Phase 1 — Core schema, identity, and sync
First execution action: replace TODO.md Current Milestone with this six-phase milestone and checkable subtasks; move the completed work-time milestone into Completed Tasks.
Add organization, accounts, scoped roles, teams, clients, projects, domain events, audit logs, and job infrastructure.
Backfill current admins, employees, tasks, reports, time entries, and company plans.
Implement email/password login, refresh sessions, invitation/reset flow, and Telegram-to-account linking.
Introduce shared task/time/report application services and transactional events/outboxes.
Add WebSocket replay and a PostgreSQL-backed worker service.
Gate: migration rehearsal passes on a production-shaped snapshot; old bot/admin/Mini App behavior remains functional.
Phase 2 — Design system and application shell
Build semantic design tokens, light/dark modes, typography, inputs, menus, sheets, tables, empty/error/loading states, and motion primitives.
Replace local page-state navigation with React Router and role-aware navigation.
Build worker, manager, administrator, contractor, and client-auditor shells.
Add accessibility and reduced-motion test fixtures.
Gate: responsive shell, authentication, permission-driven navigation, and core components pass visual and accessibility review.
Phase 3 — Projects and task execution
Deliver client/project setup, members, rates, budgets, and project dashboards.
Migrate the current board to five workflow columns.
Add drag/drop, swimlanes, hierarchy, multi-assignee support, checklists, dependencies, comments, attachments, undo, and conflict handling.
Add saved Board/List/Timeline/Calendar views.
Upgrade Telegram commands and Mini App cards to the same task service.
Gate: task changes remain consistent across browser, Mini App, bot, and simultaneous WebSocket sessions.
Phase 4 — Time, check-ins, and reports
Add unified Office/Remote/Break punch clock and project/task time allocation.
Build worker dashboard, configurable check-in cards, personal KPI widgets, and timer recovery.
Deliver markdown report editor, attachments, revision comments, approval transitions, batch review, and AI draft hooks.
Preserve existing Telegram daily/monthly workflows as alternative entry points.
Gate: no overlapping/open duplicate intervals; utilization and report totals reconcile with source entries.
Phase 5 — Capacity, analytics, and planning
Deliver employee profiles, skills, hierarchy, shifts, time off, allocations, and capacity heatmap.
Add project budget burn, billable ratio, utilization, completion, deadline, and report-compliance analytics.
Add OKRs, key results, milestones, roadmaps, and task/project contribution links.
Add currency snapshot-based planning.
Gate: KPI formulas have deterministic fixtures and permission-safe drill-downs.
Phase 6 — AI, voice, calendar, and hardening
Deliver web voice capture, asynchronous transcription, draft review, and OYUNS action tools.
Add AI-assisted report drafting, team summaries, task breakdown, and safe reallocation suggestions.
Add authenticated Google Calendar synchronization.
Ship MN/EN/RU UI dictionaries, retaining Mongolian as the default.
Run load, security, accessibility, backup/restore, incident, and failure-recovery exercises.
Roll out by feature flag: internal administrators → managers → pilot team → all employees → contractors/client auditors.
Gate: operational dashboards, alerts, runbooks, data retention, and rollback procedures are approved.
6. Test Plan and Acceptance Scenarios
Automated coverage
Migration tests from every existing Alembic head, including task status mapping and time-entry reconciliation.
RBAC matrix tests for all six roles and team/project/client scopes.
Unit tests for dependency cycles, hierarchy rules, interval overlap, breaks, local-midnight splitting, utilization, billable ratios, capacity, and currency snapshots.
API tests for idempotency, optimistic concurrency, pagination, filtering, batch approvals, attachment authorization, and rate limiting.
WebSocket tests for reconnect/replay, ordering, duplicate events, simultaneous edits, and API replica restarts.
Telegram/web contract tests proving both channels invoke identical application services.
End-to-end browser tests for worker day flow, manager delegation, approval, project setup, capacity rebalancing, and OKR linkage.
Keyboard, screen-reader, WCAG contrast, reduced-motion, reduced-transparency, and 200% text-size tests.
Performance tests for large boards, 10,000-row lists, capacity grids, and notification bursts.
AI contract tests for schema validation, confirmation boundaries, language selection, prompt injection resistance, unavailable-provider fallback, and unauthorized context exclusion.
Calendar tests for OAuth expiry, duplicate webhooks, event conflicts, disconnects, and provider outages.
Sentry tests for trace correlation across API, worker, bot, event, and notification delivery.
Acceptance scenarios
A web clock action appears in Telegram /worktime and another open browser within two seconds.
Starting lunch from Mini App pauses productive time and resuming from web restores the previous work mode.
A manager drags a task to Review; the worker sees the same position without reload and receives only one applicable notification.
Concurrent task edits produce a recoverable conflict rather than silent overwrite.
A member cannot view another team’s private report or rates; a client auditor sees only explicitly assigned client data and no employee-private metrics.
A report can be drafted by AI, edited, submitted, revision-requested, resubmitted, batch-approved, and fully audited.
Capacity reflects shifts, approved leave, project allocations, and task estimates without double-counting.
Historical project totals do not change when exchange rates or project rates later change.
AI and Chimege failure leave manual task/report creation available.
Google Calendar disconnection stops sync but never deletes or corrupts OYUNS tasks.
Assumptions and Defaults
One company is served by the deployment, with organization keys retained for future isolation.
Internal PSA is included; invoicing, tax, payment collection, and accounting exports are not.
Employees use email/password in normal browsers and may also use their linked Telegram identity.
PostgreSQL remains the system of record and initial event/job backbone.
REST and WebSockets are the public application interfaces; no GraphQL or gRPC layer is added.
Docker Compose on self-hosted Dokploy remains the production environment. Attachments use the private local volume mounted by the API and worker services; temporary voice data remains short-lived and is not promoted to durable storage.
Mongolian is the default locale, Asia/Ulaanbaatar the default timezone, and MNT the base reporting currency.
The production browser and Mini App use `erp.oyuns.mn`; `artur.oyuns.mn` remains a legacy administration compatibility domain. `TODO.md` is synchronized before and throughout implementation.
