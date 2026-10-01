# OYUNS ERP

A multi-tenant work platform for companies: tasks, projects, plans, work time, HR, reports, contracts, chat and calls, CRM, budgeting and payroll — with a built-in AI agent (**OYUNS**) and a Telegram companion bot. Everything is available through three channels on one shared core: a **web workspace**, **Telegram** (bot + Mini App) and **native iOS/Android apps**.

- **Production:** https://erp.oyuns.mn (Dokploy on a VPS). Legacy admin host: https://artur.oyuns.mn.
- **Legal pages:** [Privacy policy](https://erp.oyuns.mn/privacy) · [Terms of use](https://erp.oyuns.mn/terms)
- **Default UI language:** Mongolian (`mn`), with English and Russian translations.

> The repository started as a Telegram daily-survey tracker for one sales team. It has since grown into OYUNS ERP. The original check-in surveys still exist, but only for the primary tenant and are **off by default** (see [Legacy check-in surveys](#legacy-check-in-surveys)).

## Contents

1. [What is in the box](#what-is-in-the-box)
2. [Architecture](#architecture)
3. [Tech stack](#tech-stack)
4. [Repository layout](#repository-layout)
5. [Quick start (local)](#quick-start-local)
6. [Multi-tenancy and licensing](#multi-tenancy-and-licensing)
7. [Roles, permissions and workspace modes](#roles-permissions-and-workspace-modes)
8. [OYUNS AI agent](#oyuns-ai-agent)
9. [Telegram bot and Mini App](#telegram-bot-and-mini-app)
10. [Notifications and background jobs](#notifications-and-background-jobs)
11. [Integrations](#integrations)
12. [Mobile apps and OTA updates](#mobile-apps-and-ota-updates)
13. [Deployment (Dokploy)](#deployment-dokploy)
14. [Testing](#testing)
15. [Further documentation](#further-documentation)

---

## What is in the box

### Workspace modules (web, Mini App, mobile)

| Area | What it does |
|------|--------------|
| **Today** (`/`) | Customisable widget canvas: world clock, work time, KPIs, quick actions, tasks, news, mini calendar, timer, notes. Drag/resize grid, widget library, layout saved per user. |
| **Work time** (`/worktime`) | Clock in/out (office, remote, pause) via web, Telegram, **dynamic QR** on an office display (`/worktimeqr`) and **geofenced** location check. QR and location can be toggled per organization. Exports (CSV/Excel) and per-employee stats. |
| **HR** (`/hr`) | Employee profiles, departments, invites, time off, shared worker lifecycle, platform roles per employee. |
| **Projects, tasks, capacity** | Kanban/list tasks with assignees, reviewers, priorities and deadlines; projects, milestones, resource allocation and team capacity. |
| **Calendar** | Planning calendar with collaboration items and **two-way Google Calendar sync**. |
| **Reports** (`/reports`) | Work reports with configurable periods (daily, weekly, monthly, quarterly, half-yearly, yearly, custom), department reports, approvals, and an AI summary/export for managers. |
| **Plans** (`/plans`) | Company plan items and ideas, month by month. |
| **Contracts** (`/contracts`) | Six-step contract lifecycle, contract registry (codes, groups, parties, amounts, penalties, links), expiry reminders and a contract **archive**. |
| **Chat and calls** (`/chat`) | Workspace chat with attachments, a `/` menu to share tasks, plans, contracts and reports (recipient access is re-checked on every read), and voice/video calls (Socket.IO signaling + WebRTC). |
| **Company files** | Shared folder library with per-folder access grants, trash, ZIP download and full-text search. Uploads are scanned by ClamAV. |
| **News** (`/announcements`) | Announcements with Markdown, cover image and gallery, shown in the Today widget. |
| **Analytics** | Work-hour distribution and KPI views. |
| **Knowledge base** | Admin-curated articles plus indexed files, used by the AI agent. |

### ERP modules (toggle per organization)

| Module | Notes |
|--------|-------|
| **CRM** | Customers (`erp_parties`) and activities with reminders. See [`docs/crm-module.md`](docs/crm-module.md). |
| **Budget** (*Төсөв, гүйцэтгэл*) | Budgets linked to ledger accounts, plan-vs-actual analysis, Excel import/export. See [`docs/budget-module.md`](docs/budget-module.md). |
| **Payroll** (*Цалин*) | Mongolian payroll: monthly runs, social-insurance and tax rules, tax benefits, rule studio, salary slips, bank remittance, GL postings, Excel input template. See [`docs/payroll-architecture.md`](docs/payroll-architecture.md). |
| **Chart of accounts** (*Дансны төлөвлөгөө*) | Hierarchical accounts with purposes and bank details; accounting core (documents, GL, import) underneath payroll and budget. |

Only `crm`, `budget` and `payroll` are switchable (Settings → Modules). Each enabled module adds its own menu entry; there is no ERP hub page any more.

### Administration

Settings are grouped into organization (profile, branding, modules, custom domains), people (users, role builder, permissions), workflows (work time, report policy), integrations (Telegram bot, notifications, Google), AI (model, access matrix, voice), and security (authentication, license, 2FA).

### Operator console (`/platform`)

A separate console for the platform operator: create tenants, issue and revoke licenses, manage plans and seats, view audit logs. Operators have their own accounts, token key and mandatory TOTP two-factor login.

---

## Architecture

```
                         erp.oyuns.mn  (Dokploy / Traefik)
                                 │
                       ┌─────────┴──────────┐
                       │  frontend (nginx)  │  React SPA + static assets
                       └───┬────────────┬───┘
                 /api/*    │            │  /socket.io/*
                           ▼            ▼
              ┌───────────────────┐  ┌──────────────────┐
              │ backend (FastAPI) │  │ call-signaling   │  Node + Socket.IO
              │  uvicorn :8000    │  │      :8020       │  (Redis adapter)
              └──┬──────┬─────┬───┘  └────────┬─────────┘
                 │      │     │               │
        ┌────────┘      │     └──────┐        │
        ▼               ▼            ▼        ▼
 ┌─────────────┐  ┌───────────┐  ┌────────┐  ┌───────┐
 │ PostgreSQL  │  │   Redis   │  │ ClamAV │  │ files │  private volumes:
 │ 15+pgvector │  │           │  │        │  │       │  knowledge, attachments,
 └──────▲──────┘  └───────────┘  └────────┘  └───────┘  avatars, OTA bundles
        │
        ├── bot     (python -m app.bot.main)   aiogram multi-bot poller + APScheduler
        └── worker  (python -m app.worker)     PostgreSQL job queue (SKIP LOCKED)
```

| Service | Role |
|---------|------|
| `frontend` | nginx serving the Vite build; proxies `/api/` (prefix stripped) to `backend` and `/socket.io/` to `call-signaling`; serves Apple/Android app-association files. |
| `backend` | FastAPI API. Runs `alembic upgrade head` on start (`start.sh`). Exposes `/health`. |
| `bot` | One Telegram long-polling process hosting **one bot per tenant** (`BotPool`) and the APScheduler jobs (reminders, digests, reconciliation). Must run as a **single replica**. |
| `worker` | Durable job runner: auth e-mails, Google Calendar sync, knowledge/file indexing. Jobs are leased with `SKIP LOCKED`, so more replicas are safe. Runs migrations first. |
| `call-signaling` | Socket.IO signaling for chat calls; authorises through the backend; shares state via Redis. |
| `redis` | AI response cache, QR rate limits, call signaling state. |
| `clamav` | Virus scanning for uploaded files and attachments. |
| `db` | `pgvector/pgvector:pg15` (the migrations create the `vector` extension). |
| MCP edge *(optional)* | `app/mcp_server.py`: a stateless MCP (Streamable HTTP) server that exposes the governed OYUNS tool catalog to external MCP clients. Off by default; see [`docs/mcp-server-architecture.md`](docs/mcp-server-architecture.md). |

**API surface.** Routers are mounted without a global prefix; the proxy adds `/api`. Current-generation endpoints live under `/v1/*` (`/v1/auth`, `/v1/hr`, `/v1/erp`, `/v1/chat`, `/v1/calls`, `/v1/contracts`, `/v1/tenant`, `/v1/platform`, `/v1/mobile`, …). The older unversioned routes (`/auth`, `/employees`, `/questions`, `/tasks`, `/miniapp`, `/knowledge`, …) remain for the legacy workspace and the Mini App. Real-time events are delivered over a WebSocket with cursor-based replay.

---

## Tech stack

| Layer | Technologies |
|-------|--------------|
| Backend | Python 3.11, FastAPI 0.115, SQLAlchemy 2.0 (async, asyncpg), Alembic, Pydantic 2, PostgreSQL 15 + pgvector, Redis |
| Auth | JWT (python-jose) with bcrypt/argon2 password hashing, refresh sessions in cookies, Telegram OIDC (PKCE) for browser and native login, signed `initData` (HMAC) for the Mini App, TOTP 2FA for operators, Ed25519 license tokens |
| Telegram | aiogram 3.13 (FSM, role-based menus, multi-bot), APScheduler 3.10 |
| AI | OpenAI Responses API (GPT-5.6 family by default), embeddings + pgvector, OpenAI Realtime (voice calls), Chimege (Mongolian STT/TTS), ElevenLabs (TTS/STT), `dateparser` for natural-language dates |
| Documents | openpyxl, python-docx, python-pptx, pypdf, Pillow |
| Frontend | React 19, TypeScript 5, Vite 8, **Astryx design system** (`@astryxdesign/core`, StyleX), Tailwind CSS 3 (legacy screens), react-router 7, TanStack Query 5 and Table, Zustand 5, i18next, TipTap, Recharts, dnd-kit, ZXing (QR scanning), Socket.IO client |
| Mobile | Capacitor 8 (iOS + Android, bundle `mn.oyuns.workspace`), push (FCM/APNs), self-hosted OTA updates via `@capgo/capacitor-updater` |
| Realtime/calls | Node 22 + Socket.IO + Redis adapter (`server/`), WebRTC (optional TURN) |
| Security | PostgreSQL row-level security, ORM tenant guard, ClamAV, Fernet-encrypted secret box for stored credentials |
| Observability | Sentry (API, bot, frontend) |
| Testing | pytest, Vitest + Testing Library, Playwright, axe-core |
| Hosting | Docker Compose on Dokploy (VPS); local development with the same Compose file |

---

## Repository layout

```
.
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, router registration, lifespan (admin seed)
│   │   ├── worker.py          # PostgreSQL-backed job worker
│   │   ├── mcp_server.py      # optional MCP edge; mcp_executor.py = signed private executor
│   │   ├── bot/               # aiogram handlers, menus, middlewares, scheduler, multi-bot pool
│   │   ├── core/              # config, database, security, deps, tenancy, tenant middleware, roles
│   │   ├── models/            # SQLAlchemy models (core, contracts, CRM, budget, platform, announcements)
│   │   ├── routers/           # REST routers (auth, tasks, chat, calls, contracts, tenant, platform, ...)
│   │   ├── hr/  crm/  budget/ # module packages (router, service, schemas)
│   │   ├── erp/               # ERP core: accounting, chart of accounts, role catalog
│   │   ├── payroll/           # monthly engine, tax rules, Excel templates, GL postings
│   │   ├── services/          # business logic; ai_gateway/ (agent), mcp/ (tool catalog), integrations
│   │   └── observability/     # Sentry setup
│   ├── alembic/versions/      # ~110 migrations
│   ├── scripts/               # platform_admin, oyuns_eval, live verification scripts
│   ├── tests/                 # pytest suites
│   └── start.sh               # migrate, then uvicorn
├── frontend/
│   ├── src/
│   │   ├── pages/             # route-level screens
│   │   ├── components/        # shared components; today/ (widget canvas), accounts/, crm/, budget/, payroll/
│   │   ├── console/           # operator console (/platform)
│   │   ├── api/  hooks/  store/  platform/  theme/
│   │   └── i18n.ts            # mn / en / ru
│   ├── e2e/                   # Playwright specs
│   ├── ios/  android/         # Capacitor native projects
│   ├── scripts/               # native sync and OTA upload/promote/rollback scripts
│   └── nginx.conf
├── server/                    # Socket.IO call-signaling service (TypeScript)
├── types/                     # TypeScript types shared by frontend and server
├── ops/                       # nginx samples, SQL for least-privilege DB roles, hardening exercises
├── docs/                      # product and architecture documents
├── docker-compose.yml         # local / VPS compose
├── docker-compose.dokploy.yml # production (Dokploy)
└── docker-compose.hardening.yml / docker-compose.test.yml
```

---

## Quick start (local)

### Prerequisites

- Docker with Compose v2
- Node.js 22+ (only for frontend hot reload or native builds)
- A Telegram bot token from [@BotFather](https://t.me/BotFather) is **optional**; the web app works without it

### 1. Prepare

```bash
git clone https://github.com/petereen/tracker_artur.git
cd tracker_artur
cp .env.local.example .env
# docker-compose.yml attaches the frontend to an external network used by the shared edge proxy.
docker network create web-edge
```

### 2. Run

```bash
docker compose up -d
```

Migrations run automatically on start.

| URL | What |
|-----|------|
| http://localhost:3010 | Web app (nginx, proxies `/api`) |
| http://localhost:8010 | API directly (bound to localhost; `/health`, `/docs`) |

### Frontend with hot reload

```bash
docker compose up -d db redis backend call-signaling
cd frontend
npm install
npm run dev -- --host 127.0.0.1     # http://localhost:5173
```

Vite proxies `/api` to the backend (`http://localhost:8010`) and `/socket.io` to the signaling service.

### Backend without Docker

```bash
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt
alembic upgrade head          # needs a reachable PostgreSQL
uvicorn app.main:app --reload --port 8000
python -m app.bot.main      # Telegram bot + scheduler (needs a bot token)
python -m app.worker        # background jobs
```

### Database migrations

```bash
docker compose run --rm backend alembic upgrade head
docker compose run --rm backend alembic current
docker compose run --rm backend alembic revision --autogenerate -m "describe the change"
```

Heads are checked by `tests/test_alembic_graph.py`. Legacy `organization_id` columns that are not mapped in the ORM are excluded from autogenerate in `alembic/env.py`. Migrations that create tables must describe them explicitly instead of reading `Base.metadata`, otherwise a clean install breaks when a model changes.

---

## Multi-tenancy and licensing

OYUNS ERP is a multi-tenant SaaS. The original company is the **primary tenant** (all modules, no seat limit, no license required), so existing users see no change. Full design: [`docs/multi-tenancy.md`](docs/multi-tenancy.md).

- **Tenant = `organizations` row** (slug, status `pending_activation | active | suspended | terminated`, plan, `seat_limit`, features, branding, license expiry).
- **Resolution:** from the host (`<slug>.<TENANT_BASE_DOMAIN>` or a verified custom domain) and from the JWT; a mismatch returns `403 tenant_mismatch`. Suspended tenants get 403; missing or expired licenses get `402` (except auth and tenant endpoints); a module outside the license gets `403 feature_not_licensed`.
- **Isolation in three layers:** `organization_id` filters in code, an ORM guard that raises `TenantBoundaryViolation` for foreign rows (and stamps new rows), and **PostgreSQL row-level security** on every tenant table. RLS is bypassed by superusers, so the production API must connect as the `oyuns_app` role (`ops/sql/oyuns_app_role.sql`); Alembic migrates as the database owner.
- **Licenses:** Ed25519-signed tokens verified offline (with key rotation) plus a registry for revocation. Admins activate a license in Settings → Security → License; without one the frontend shows an activation screen.
- **Seats:** enforced in the application (locking the tenant row) and by a database trigger as a backstop (`409 seat_limit_reached`).
- **Per-tenant extras:** branding (name, logo, colors), custom domains through Cloudflare for SaaS, and the tenant's own Telegram bot.
- **Operator console:** `/platform` (see above). CLI helpers:

```bash
docker compose exec backend python -m scripts.platform_admin generate-license-keys
docker compose exec backend python -m scripts.platform_admin create-operator --help
docker compose exec backend python -m scripts.platform_admin tenants
docker compose exec backend python -m scripts.platform_admin rls-status
docker compose exec backend python -m scripts.platform_admin reset-2fa --email operator@example.com
```

New module endpoints must register their prefix in `FEATURE_ROUTES` (`app/core/tenancy.py`) so license gating applies.

---

## Roles, permissions and workspace modes

- **Platform roles:** `admin`, `manager`, `team_lead`, `hr`, `member`, `contractor`, `client_auditor`, `legal_counsel`.
- **Role builder** (Settings → People → Roles and permissions): custom roles combine platform roles (never `admin`) with module permissions from a catalog of capabilities that the backend actually checks (`app/erp/role_catalog.py`).
- **ERP capabilities** guard modules (for example `parties`, `crm_activity`, `budget`, `accounts.view`, `payroll.view`). Accountant and Sales are built-in capability roles.
- **Manager/Member mode:** users with management roles can switch the whole workspace to a personal (`member`) view. The mode is enforced **server-side** through the `X-Workspace-Mode` header, so every page and API narrows to the user's own data.
- **Telegram roles come from the ERP only.** The Telegram-ID allowlist in manager settings is just a notification recipient list and grants no permissions.

---

## OYUNS AI agent

One agent serves the web assistant, team chat, the Telegram bot, the voice-call feature and (optionally) external MCP clients.

**Turn flow** (`app/services/ai_gateway/gateway.py`):

1. Build context: who is asking, roles, department, time and time zone, a personal snapshot (my tasks, overdue items, work-time state), the data domains the user may read, preflight knowledge hits, and a digest of the previous turn's tool results.
2. Run **one** OpenAI Responses loop with all permission-scoped `oyuns_*` tools the user is allowed to call. Authorization is re-checked on every dispatch.
3. Return the answer with sources, file deliveries, a pending task preview if any, and memory for follow-ups.

Answers always come from a live model. If no model is reachable, only narrow offline fallbacks run (self-meeting task previews, lexical knowledge excerpts) with an explicit degraded notice.

**Tools** (governed catalog, `app/services/mcp/catalog.py`): `oyuns_tasks_search`, `oyuns_tasks_prepare_create`, `oyuns_tasks_prepare_update`, `oyuns_projects_search`, `oyuns_reports_search`, `oyuns_worktime_get`, `oyuns_hr_get`, `oyuns_crm_search`, `oyuns_contracts_search`, `oyuns_payroll_summary`, `oyuns_stats_get`, `oyuns_calendar_availability`, `oyuns_knowledge_search`, `oyuns_knowledge_fetch`, `oyuns_exchange_rate_get` (Mongolbank), `oyuns_erp_read`, `oyuns_records_search` / `oyuns_records_get` / `oyuns_records_aggregate`, and `oyuns_enterprise`. Web search is an optional extra for public information.

**Safety model**

- Writes are **previews only**: the agent prepares a task, the user confirms in the channel. A tool can never create or change a record by itself.
- Tool results strip internal IDs; resources are referenced through opaque references.
- Sensitive domains (payroll) are hidden in group chats.
- **Access matrix** (Settings → OYUNS AI): admins restrict the agent per section (read / create and edit). It can only narrow, never widen, a user's own rights.
- **Tenant isolation:** the gateway fails closed without a tenant. Read tools use a per-tenant connection pool on a dedicated database role (`oyuns_ai`, `NOBYPASSRLS`; see `ops/sql/oyuns_ai_role.sql`) with `app.rls_strict=on`, and can be set to refuse to run if that role bypasses RLS.
- Caches (Redis exact-match, pgvector semantic for context-free questions) are keyed by tenant. RAG, action and web-search answers are never cached.

**Models and keys.** Configure the API key, model (picked from `/v1/models` or typed in) and options under Settings → OYUNS AI (`/administration/ai/knowledge`, admin only). The organization setting takes precedence over deployment-level defaults.

**Voice**

- Telegram voice/audio/video notes: Chimege STT (OpenAI fallback) → agent → text, plus Chimege TTS when enabled.
- **Voice call** (phone button in the assistant chat): engine selectable per organization — `auto`, OpenAI Realtime (WebRTC, ephemeral client secret, read-only tools), Chimege (Mongolian, browser VAD + step-by-step pipeline) or ElevenLabs (Scribe STT + streamed TTS). `auto` picks Chimege for Mongolian and OpenAI Realtime otherwise.

**Knowledge.** Admins maintain articles under Settings → OYUNS AI; company files are indexed by the worker (pgvector). Inactive articles never reach the model.

**Learning loop.** Requests the agent cannot classify go to a protected review queue (`/assistant-learning/unknown`); an admin can promote a verified answer into a knowledge article.

**Evaluation and live checks**

```bash
cd backend
python -m scripts.oyuns_eval --email <account>             # live mn/ru/en prompt evaluation (needs a key)
python scripts/verify_ai_gateway_live.py     # live check, needs a model key
```

Design notes: [`docs/ai-assistant-prompt-architecture.md`](docs/ai-assistant-prompt-architecture.md), [`docs/enterprise-agent-tools.md`](docs/enterprise-agent-tools.md), [`docs/assistant-reliability.md`](docs/assistant-reliability.md), [`docs/mcp-server-architecture.md`](docs/mcp-server-architecture.md).

---

## Telegram bot and Mini App

The bot is a **companion to the ERP**, not a separate product: identities, roles and data all come from the ERP.

- **One bot per tenant.** A tenant admin connects their own bot under Settings → Integrations → Telegram bot: paste the BotFather token, then open the `t.me/<bot>?start=oyuns-<code>` handshake link to activate it and bind the admin's Telegram. Tokens are stored encrypted. The primary tenant keeps using the platform bot until it connects its own.
- **Update classification** (`app/bot/middlewares.py`): bot → tenant, Telegram ID → employee of that tenant. Unregistered users (or employees of another tenant) get an informational message with their Telegram ID and are told to contact the ERP admin or HR; no handler runs. Exceptions: invite links, handshake links, and `/myid`.
- **Roles from the ERP** (direct assignments plus role-builder roles). The menu follows the role and refreshes on the next message after a role change.
- **Mini App** (`/tg`): a vertical task board authenticated with signed Telegram `initData`, opened from the menu button ("Самбар") or `/app`.
- **Telegram login** to the web app and native apps uses OIDC with PKCE.

### Commands

| Command | Who | Description |
|---------|-----|-------------|
| `/start`, `/help`, `/myid` | everyone | Registration, help, your Telegram ID |
| `/app` | everyone | Open the Mini App |
| `/daystart`, `/dayend`, `/remotestart`, `/remoteend`, `/daypause`, `/worktime` | everyone | Work-time clock (office start asks for location when geofencing is on) and today's hours |
| `/mytasks`, `/done`, `/snooze`, `/review` | everyone | My tasks, complete, postpone, submit for review |
| `/task`, `/assigned`, `/dashboard` | admin, manager | Create tasks quickly, tasks I assigned, task dashboard |
| `/monthly_digest` | admin, manager | Monthly report digest |
| `/today`, `/my_stats`, `/leaderboard`, `/summary`, `/week`, `/blockers` | primary tenant only | [Legacy check-in surveys](#legacy-check-in-surveys) |

Free text and voice go to the OYUNS agent: create or delegate tasks (always through a confirmation draft), ask about tasks, plans, reports, work time, HR, CRM, contracts and knowledge, or plan the day. Telegram replies use the same language as the question (mn/en/ru).

Employees can only assign tasks to themselves; managers can assign to anyone, including "all active employees" (one draft, one task per recipient after confirmation).

### Legacy check-in surveys

The original product — daily survey questions, reminders, streaks, a top-3 leaderboard, a "soft mode" first week and manager summaries — is kept for the primary tenant. It is disabled by default and gated by the `checkin` notification category and the `legacy_workspace` feature. Product rules: at most 5 required questions per employee, top-3 ranking only (no anti-ranking), reminders follow the employee's time zone, answers are stored indefinitely.

---

## Notifications and background jobs

- **Categories:** tasks, reports, work time, calendar, contracts, HR, CRM, payroll, digests, check-in, system. Tenants set defaults (enable, platform, Telegram, "employees may override"); users override in their profile. Preferences are applied at creation, again at outbox delivery (`skipped`), and in every bot job.
- **Quiet hours and working window** (default 09:00–20:00, Mon–Fri, DST-safe): routine pushes outside the window are deferred to the next working start.
- **Digests:** employee morning/evening, manager morning overview with escalation, monthly report digest per tenant. Empty digests are not sent.
- **Reminders:** task deadlines (default 1 day / 2 hours / at due time), calendar and project deadlines, contract expiry, CRM activities, work-time start/end, report periods (with a grace window), birthdays. Overdue tasks produce one ping to the assignee and an escalation after `overdue_escalation_days` working days.
- **Outbox:** pushes created by the API go to `notification_outbox`; the bot drains it every minute. Native push uses FCM/APNs when enabled.
- **Where jobs run:** APScheduler lives **only in the bot process** (reconciliation jobs run every 1–15 minutes). The `worker` runs durable queue jobs. Scheduler jobs still execute in a system context rather than a tenant context; the manager digest for all tenants follows the primary tenant's schedule.

---

## Integrations

Most integrations are configured **in the UI per organization**: the OpenAI key and model, Chimege tokens, ElevenLabs key, the tenant's own Telegram bot, notification defaults, report policy and branding. Secrets stored this way are encrypted and only their last four characters are returned by the API.

| Integration | Purpose | Details |
|-------------|---------|---------|
| **Telegram** | Bot, Mini App, OIDC login | Per-tenant bots under Settings → Integrations |
| **OpenAI** | Agent, embeddings, STT, Realtime voice | Settings → OYUNS AI |
| **Chimege** | Mongolian speech-to-text and text-to-speech | Settings → OYUNS AI |
| **ElevenLabs** | Streaming TTS and Scribe STT for calls | Settings → OYUNS AI |
| **Google Calendar** | Per-account OAuth, outbound and optional bidirectional sync with push channels | [`docs/google-calendar-sync.md`](docs/google-calendar-sync.md) |
| **Mongolbank rates** | Exchange rates for the agent and work-time snapshots | built in |
| **Resend (SMTP)** | Verification and password-reset e-mail | built in |
| **FCM / APNs** | Native push notifications | [`docs/mobile-release.md`](docs/mobile-release.md) |
| **Cloudflare for SaaS** | Tenant custom domains with managed certificates | Settings → Organization → Custom domain; [`docs/multi-tenancy.md`](docs/multi-tenancy.md) |
| **ClamAV** | Virus scan of uploads | built in |
| **Ebarimt** | Taxpayer lookup when creating CRM customers | built in |
| **MCP clients** | External access to the governed tool catalog (opt-in) | [`docs/mcp-server-architecture.md`](docs/mcp-server-architecture.md) |
| **Sentry** | Error tracking | API, bot and frontend |

---

## Mobile apps and OTA updates

The same React/Vite source is wrapped by Capacitor 8 (`mn.oyuns.workspace`). Native sessions are kept in secure storage; push tokens are registered through `/v1/mobile`. Web-asset updates are delivered over the air from the OYUNS backend (no third-party update cloud): bundles are uploaded to a `staging` channel, then promoted to `production`, with rollback.

```bash
cd frontend
npm run native:prepare:ios        # test, build, cap sync, open Xcode
npm run native:prepare:android    # test, build, cap sync, open Android Studio (JDK 21)
npm run ota:upload:staging        # upload a bundle
npm run ota:promote:production
npm run ota:rollback:production
npm run ota:doctor
```

Anything that changes native plugins, entitlements or signing needs a new store binary. Signing prerequisites, push setup and the full runbook: [`docs/mobile-release.md`](docs/mobile-release.md). CI workflows for staging and production OTA are in `.github/workflows/`.

The mobile web layout (≤ 800 px) behaves like a native app: bottom tab bar, "More" sheet, pull-to-refresh, and bottom-sheet dialogs. The site is also installable as a PWA.

---

## Deployment (Dokploy)

Production runs from [`docker-compose.dokploy.yml`](docker-compose.dokploy.yml) on a VPS.

1. In Dokploy, create a Compose application from this repository and provide its environment through Dokploy (see [`.env.example`](.env.example) for the full list).
2. In the **Domains** tab, attach the public domain to the `frontend` service on port 80. Only the frontend is exposed; the API, bot, worker and signaling stay on the internal network.
3. **Pushing to `origin/master` deploys.** New routes appear within seconds. Verify with an unauthenticated protected route (`403` = present, `404` = missing) and by checking that the `assets/index-*.js` hash changed.
4. The backend migrates on start. If a migration fails and recovery mode is enabled, the API starts in recovery mode: run `alembic upgrade head` from the container terminal and redeploy. The worker refuses to run against an outdated schema.
5. For real tenant isolation create the least-privilege roles (`ops/sql/oyuns_app_role.sql`, `ops/sql/oyuns_ai_role.sql`) and connect the API and the AI agent through them. Custom tenant domains additionally need the catch-all Traefik router described in `docs/multi-tenancy.md`.
6. Keep the `bot` service at **one replica**. Persist the `pgdata`, `attachment_uploads`, `knowledge_uploads`, `avatar_uploads` and `ota_bundles` volumes and back up PostgreSQL off-host.

Operational runbooks: [`docs/production-hardening.md`](docs/production-hardening.md) (backup/restore, load and failure exercises via `ops/hardening-exercises.sh`) and [`docs/worktime-qr.md`](docs/worktime-qr.md) (office QR display provisioning).

> The shared working tree is edited by several people and agents. Commit only your own hunks and verify in a clean `git worktree` (type-check, tests, build) before pushing, because a push to `master` is a production deploy.

---

## Testing

```bash
# Backend (Python 3.11)
cd backend
pip install -r requirements.txt -r requirements-test.txt
python -m pytest -q

# Frontend
cd frontend
npm test                    # Vitest
npm run build               # tsc -b && vite build
npm run test:e2e            # Playwright (install Chromium first)

# Call signaling
cd server && npm test
```

Database-backed suites (enterprise foundation, chat share and reports, AI tools, multi-tenant end-to-end, budget, chart of accounts, contracts) need a disposable PostgreSQL and are skipped unless the corresponding opt-in variable is set; the variable names are at the top of each test module. A containerised run of everything is available with `docker compose -f docker-compose.test.yml up --build --abort-on-container-exit`.

For a manual check of the monthly report digest, a manager can send `/seed_monthly_digest` (creates approved `monthly_test` reports) and then `/test_monthly_digest` to the bot. These handlers are not listed in the bot menu.

---

## Further documentation

| Document | Topic |
|----------|-------|
| [`docs/portal-spec.md`](docs/portal-spec.md) | Product specification: how the bot, Mini App and web workspace relate (no tech stack) |
| [`docs/multi-tenancy.md`](docs/multi-tenancy.md) | Tenancy, RLS, licenses, seats, per-tenant bots and custom domains |
| [`docs/mcp-server-architecture.md`](docs/mcp-server-architecture.md) | MCP edge and tool governance |
| [`docs/enterprise-agent-tools.md`](docs/enterprise-agent-tools.md), [`docs/ai-assistant-prompt-architecture.md`](docs/ai-assistant-prompt-architecture.md), [`docs/assistant-reliability.md`](docs/assistant-reliability.md) | AI agent |
| [`docs/payroll-architecture.md`](docs/payroll-architecture.md), [`docs/payroll-rule-studio.md`](docs/payroll-rule-studio.md), [`docs/payroll-setup-workflow.md`](docs/payroll-setup-workflow.md) | Payroll |
| [`docs/crm-module.md`](docs/crm-module.md), [`docs/budget-module.md`](docs/budget-module.md) | CRM and budget modules |
| [`docs/enterprise-implementation.md`](docs/enterprise-implementation.md), [`docs/erp-core-configuration-fix.md`](docs/erp-core-configuration-fix.md), [`docs/erp-dayansoft-gap-analysis.md`](docs/erp-dayansoft-gap-analysis.md) | ERP foundation and gap analysis |
| [`docs/google-calendar-sync.md`](docs/google-calendar-sync.md), [`docs/worktime-qr.md`](docs/worktime-qr.md), [`docs/provider-configuration.md`](docs/provider-configuration.md) | Integrations |
| [`docs/mobile-release.md`](docs/mobile-release.md), [`docs/production-hardening.md`](docs/production-hardening.md) | Release and operations runbooks |
| [`frontend/AGENTS.md`](frontend/AGENTS.md), [`frontend/ASTRYX-SETUP.md`](frontend/ASTRYX-SETUP.md) | Astryx design-system conventions for new UI |
| [`CLAUDE.md`](CLAUDE.md) | Working notes for AI coding agents: change log, gotchas and per-feature details |
