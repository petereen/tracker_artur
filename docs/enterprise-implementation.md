# Enterprise PM/PSA implementation

## Delivered foundation

The enterprise layer is additive. Existing Telegram, Mini App, and unversioned
admin APIs remain available while new clients use `/api/v1`.

- `q5r6s7t8u9v0` creates the organization, account/RBAC, team, client, project,
  task relation, resource, check-in, OKR, audit/event, job, and calendar tables.
- Existing administrators are backfilled into `user_accounts`; fresh databases
  receive the same mapping during application startup.
- Existing tasks keep their legacy `status` for compatibility and gain the
  five-state `workflow_status`, version, organization, project, hierarchy, and
  ordering fields.
- Existing work intervals remain in `work_time_entries` and gain the canonical
  employee, project/task, work/break, billable, approval, and version fields.
- Enterprise mutations write an audit record and durable domain event in the
  same transaction. `/api/v1/realtime` replays events from a cursor.

## Services

Production now consists of four application roles:

1. `backend`: FastAPI REST and WebSocket API.
2. `bot`: single-replica Telegram long-polling and Telegram notification work.
3. `worker`: PostgreSQL `SKIP LOCKED` jobs with leases and bounded retries.
4. `frontend`: routed React SPA and Telegram Mini App behind Nginx.

No Redis service is required. The frontend proxy must preserve WebSocket
upgrade headers; the repository Nginx configuration already does so.

## Authentication and authorization

- Enterprise access tokens expire after 15 minutes by default and stay only in
  frontend memory.
- Refresh tokens are random, stored only as SHA-256 hashes, rotated on every
  refresh, and sent as `HttpOnly`, `Secure`, `SameSite=Lax` cookies.
- New passwords use Argon2id. Migrated bcrypt hashes are accepted once and
  transparently upgraded after successful login.
- Roles are `admin`, `manager`, `team_lead`, `member`, `contractor`, and
  `client_auditor`. Project/client auditor scopes and employee project
  memberships are enforced by server queries, not frontend navigation.

Set `AUTH_COOKIE_SECURE=false` only for local HTTP development. Production must
retain the default `true` value.

## Primary API surface

- Identity: `/api/v1/auth/*`
- Teams/resources: `/api/v1/teams`, `/capacity`, `/time-off`,
  `/resource-allocations`
- PSA: `/api/v1/clients`, `/projects`, project members and rates
- Work: `/api/v1/tasks`, assignees, dependencies, check items
- Time: `/api/v1/clock/*`, `/time-entries`
- Reports/check-ins: `/api/v1/reports`, `/checkin-templates`
- Planning: `/api/v1/objectives`, key results, milestones, analytics
- Integrations: `/api/v1/assistant/drafts`, `/voice/transcriptions`,
  `/integrations/google-calendar/*`
- Realtime: `/api/v1/realtime?token=...&cursor=...`

Task creation and clock commands accept `Idempotency-Key`. Task changes accept
`If-Match` with the current integer version and return `409` with the latest
record when another user won the race.

## Rollout

1. Back up PostgreSQL and rehearse `alembic upgrade q5r6s7t8u9v0` on a restored
   production-shaped database.
2. Deploy backend and worker before the new frontend.
3. Verify `/health`, enterprise admin login, `/api/v1/auth/me`, and WebSocket
   replay through the production proxy.
4. Enable administrators and managers, then one pilot team, then all workers.
5. Keep legacy task/report/admin routes for two releases before any contract
   removal.

## Validation performed

- SQLAlchemy mapper configuration and PostgreSQL DDL compilation: 57 tables.
- Alembic revision graph: one head, `q5r6s7t8u9v0`.
- Focused backend enterprise/regression suite: 46 passed.
- Frontend semantics/accessibility tests: 2 passed.
- TypeScript plus code-split Vite production build: passed.

The full pre-existing backend suite currently reports 202 passes and eight
failures in unrelated legacy tests (assistant draft fakes, exchange-rate
fixture, digest async mock, Telegram token fixture, sequential test helper,
and one open-interval duration expectation). These were not rewritten as part
of the enterprise change.

## Provider-dependent follow-up

Resend SMTP authentication email, private local-volume attachment storage, signed-state
Google OAuth, encrypted Calendar tokens, and outbound task-event synchronization
are implemented. They stay safely disabled until their environment variables
are supplied; see `docs/provider-configuration.md`.

Attachments use the mounted local Dokploy volume; Azure is not required for this
self-hosted deployment.

Inbound Calendar push synchronization, scoped analytical drill-downs, collaboration
UI, and production-shaped exercise scripts are implemented. Live provider, load,
migration, and restore rehearsals still require operator-authorized infrastructure;
follow `docs/production-hardening.md` and record the evidence in the deployment ticket.
