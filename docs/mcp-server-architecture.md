# OYUNS MCP Server Architecture & Specification

**Status:** implemented as an opt-in runtime; disabled by default pending a
tenant-scoped canary and production transport review.  
**Audience:** OYUNS platform, security, and AI-integration engineers.  
**Scope:** an MCP server that presents governed OYUNS ERP, PostgreSQL-backed
records, and indexed company knowledge to the OYUNS AI agent.

This document is a public-contract specification for the MCP boundary. It does
not make database tables, internal FastAPI routes, storage keys, or service
credentials public interfaces.

## 1. Goals and design principles

The MCP server lets an LLM retrieve permitted company information and prepare
approved ERP actions without granting the LLM direct database or ERP access.

- PostgreSQL remains the system of record; pgvector supports knowledge search.
- The application, never the model, is authoritative for identity, tenant,
  permissions, record visibility, and mutation success.
- Tools express stable business capabilities, not physical tables or generic
  CRUD. No tool accepts raw SQL, arbitrary table names, storage paths, or an
  unrestricted `execute` operation.
- Reads return the smallest useful, cited result. Writes are always
  preview-then-confirm, actor-bound, one-time, and replay-safe.
- A refusal, no match, partial result, or upstream outage is a normal,
  structured outcome—not a reason to invent an answer.

Existing application behavior is the baseline: `ActorContext` is the unified
identity model; organization/RBAC scoping, resource policies, encrypted
assistant tool audits, and `AssistantPendingAction` confirmation records stay
owned by FastAPI application services.

## 2. Component architecture and trust boundary

```text
 Web chat / Telegram / Mini App
             |
             | authenticated OYUNS request
             v
 +----------------------+       +-------------------------+
 | OYUNS AI gateway     |-----> | OpenAI Responses API    |
 | classification +     |       | store: false            |
 | conversation policy  |       +-------------------------+
 +----------+-----------+
            |
            | MCP over HTTPS / secure tunnel
            v
 +----------------------------------------------------------+
 | OYUNS MCP edge                                            |
 | Streamable HTTP · token validation · replay defense       |
 | tool discovery · schema/version policy · rate limits      |
 +-------------------------+--------------------------------+
                           |
                           | mTLS; internal network only
                           v
 +----------------------------------------------------------+
 | FastAPI policy and tool executor                          |
 | ActorContext rehydration · RBAC/ACL · validation          |
 | projection/redaction · audit · pending-action service     |
 +----+-------------------+------------------+--------------+
      |                   |                  |
      v                   v                  v
 PostgreSQL          pgvector knowledge   files / OYUNS ERP
 organizations,      documents/chunks     tasks, projects,
 policies, audits,                       calendars, stats,
 pending actions                         people, reports
```

### 2.1 Hybrid deployment

The MCP edge is a thin, stateless service. It exposes only Streamable HTTP over
HTTPS, or is reached through an approved secure tunnel. It never connects to
PostgreSQL with a privileged database account and never independently decides
which rows a caller may read. The edge forwards an authenticated, HMAC-signed
execution envelope to an internal FastAPI executor. Production additionally
uses mTLS at the private network/mesh boundary; local Compose keeps that flag
off while preserving the signed private-network boundary.

The FastAPI executor is the policy enforcement point. It reconstructs the
current `ActorContext` from the active account on every call, including account
status, organization, employee binding, locale, and time-bounded role
assignments. The executor injects `account_id`, `organization_id`, roles,
locale, and channel; those fields are forbidden in tool input schemas.

### 2.2 Authentication and transport

- Require a short-lived JWT whose `aud` is `oyuns-mcp`, `iss` is the OYUNS
  identity service, and whose subject identifies the OYUNS account—not a
  database user.
- Bind the token to a caller/session identifier and enforce `exp`, `nbf`, `jti`,
  and a replay cache. Reject a reused `jti` for the lifetime of the token.
- Accept the MCP edge only on HTTPS with modern TLS. Keep FastAPI execution on
  a private network and require mutual TLS, certificate rotation, and a narrow
  service identity allowlist.
- Forward a generated `X-Request-Id` and a W3C-compatible trace/correlation ID.
  Do not trust a caller-supplied identity, tenant, role, or channel header.
- If a remote MCP server is registered with the Responses API, configure only
  the approved OYUNS endpoint and pass the per-turn authorization token. Never
  turn a generic proxy or a third-party MCP server into an ERP authority.

### 2.3 Failure isolation and runtime policy

| Concern | Contract |
| --- | --- |
| Database read deadline | 5 seconds, then return `unavailable` / `SOURCE_TIMEOUT` |
| ERP/application deadline | 15 seconds, then return `unavailable` / `SOURCE_TIMEOUT` |
| Retries | At most one bounded retry for idempotent, read-only, transient failures; never automatically retry confirmation or write preparation after a timeout |
| Circuit breaker | Open per dependency after configured consecutive transient failures; fail fast with a safe retry hint until the cool-down expires |
| Transaction handling | Preview creation and confirmation run in database transactions; confirmation rechecks all state before commit |
| Audit availability | An audit write is part of tool execution. If a required audit cannot be persisted, fail closed for previews/confirms and return `partial` or `unavailable` for reads according to the organization policy |

The Responses API request uses `store: false`; OYUNS remains the owner of
conversation history. Tool prompts and results use the existing encrypted
assistant audit record: content is retained for 30 days and metadata for 365
days. The MCP service must not add plaintext request/result logging.

## 3. Tool inventory taxonomy

### 3.1 Naming rule

Use exactly `oyuns_<domain>_<operation>` in lowercase snake case. A name has one
business domain and one clear action. It is stable across internal table or
router refactors.

Allowed operation words are:

- `search` for bounded filtered discovery;
- `get` or `fetch` for one opaque, authorized reference;
- `aggregate` for an aggregate rather than raw records;
- `availability` for calendar free/busy information;
- `prepare_create` or `prepare_update` for a non-mutating action preview;
- `confirm` or `cancel` for a pending action.

Never encode a role, backend technology, physical table, or an implementation
version in a tool name. For example, use `oyuns_tasks_search`, not
`postgres_tasks_select_v2` or `manager_task_admin`.

### 3.2 Initial public catalog

| Tool | Purpose | Access / result shape |
| --- | --- | --- |
| `oyuns_knowledge_search` | Hybrid keyword/semantic search over authorized company files and knowledge | Read; citations, excerpts, locators |
| `oyuns_knowledge_fetch` | Retrieve a single authorized knowledge excerpt by opaque reference | Read; excerpt only, never storage key |
| `oyuns_records_search` | Search allowlisted logical records such as people or approved company plans | Read; typed summary rows |
| `oyuns_records_get` | Fetch one permitted record via opaque reference | Read; field projection by policy |
| `oyuns_records_aggregate` | Return a count, grouping, or other allowed aggregate | Read; aggregate only |
| `oyuns_tasks_search` | Retrieve scoped tasks, blockers, and review state | Read; task summaries |
| `oyuns_projects_search` | Retrieve scoped projects, milestones, and plans | Read; project summaries |
| `oyuns_calendar_availability` | Return authorized calendar availability/events | Read; free/busy for private details |
| `oyuns_stats_get` | Return governed task, work-time, report, project, and budget metrics | Read; metric summary or table |
| `oyuns_tasks_prepare_create` | Produce a task creation preview | Preview; no task is written |
| `oyuns_tasks_prepare_update` | Produce a task update preview | Preview; no task is changed |

Confirmation and cancellation are deliberately **not MCP tools** in the first
runtime. They remain trusted Web/Telegram callback actions so the model cannot
perform the final mutation.

The catalog starts deliberately small. Add a tool only when its semantics,
authorization rules, compact input, output projection, audit fields, and test
cases are all known. Do not expose one tool per database table.

### 3.3 Tool metadata and schema contract

Every catalog entry declares the following server metadata in addition to its
MCP name, JSON Schema, and description:

| Metadata | Required value |
| --- | --- |
| `domain` | `knowledge`, `records`, `tasks`, `projects`, `calendar`, `analytics`, or `actions` |
| `access_mode` | `read` or `preview` (confirmation is channel-owned) |
| `idempotency` | `not_required` or `preview_token` |
| `required_capability` | server-enforced capability, never model supplied |
| `classification_ceiling` | highest data classification the tool may return before row/field policy reduces it |
| `latency_class` | `fast` (target 5 seconds) or `standard` (target 15 seconds) |
| MCP annotations | `readOnlyHint`, `destructiveHint`, and confirmation semantics consistent with `access_mode` |

Input schemas are strict JSON Schema objects:

- `additionalProperties` is always `false` at every object level.
- All strings, arrays, filters, dates, sort choices, and page sizes have
  explicit bounds. Inputs use business enums rather than arbitrary column or
  status names.
- Timestamps are RFC 3339 / ISO-8601 values with a numeric UTC offset. A local
  date/time without an offset is rejected when an instant is required.
- Optional values are explicitly nullable and still appear in strict schemas;
  defaults are applied only after server validation.
- Record references and page cursors are opaque, signed, actor- and
  organization-bound values. Numeric primary keys are not public identifiers.

Internally, each tool maps to allowlisted SQLAlchemy queries or application
services. Every query has a mandatory organization predicate, authorization
filter, explicit projection, deterministic sort, bounded limit, and
parameterized filters.

### 3.4 Current-to-MCP migration map

| Current application tool | MCP public name | Compatibility behavior |
| --- | --- | --- |
| `file_search_tool` | `oyuns_knowledge_search` | Map `search` and `list` into typed knowledge query modes; retain legacy tool as an internal alias during migration |
| `get_stats_tool` | `oyuns_stats_get` | Preserve the current governed metrics allowlist |
| `project_mgmt_tool` | `oyuns_tasks_search` or `oyuns_projects_search` | Split by requested entity; preserve current scoped project/plan/task semantics |
| `calendar_tool` | `oyuns_calendar_availability` | Preserve role hierarchy and private-event free/busy rules |
| `employee_directory_tool` | `oyuns_records_search` | Expose only the permitted directory projection |
| `create_task` | `oyuns_tasks_prepare_create` | Create an action preview only |
| `delegate_task` | `oyuns_tasks_prepare_create` | Same preview tool; target authority stays server validated |
| `project_mgmt_update_tool` | `oyuns_tasks_prepare_update` | Create an update preview only |
| `confirm_task_update` | Trusted Web/Telegram confirmation | Recheck actor, tenant, channel, expiry, and record version |

Legacy aliases are implementation-only and have a fixed deprecation period.
They are never advertised as new MCP tools. Removing an alias requires catalog
versioning and migration evaluation coverage.

## 4. Tool routing and dynamic discovery

### 4.1 Discovery policy

Initially present the model only an MCP server label and concise description:

> `oyuns_enterprise`: Permission-scoped company knowledge and OYUNS ERP tools
> for tasks, projects, schedules, people, and approved analytics. All actions
> require an explicit preview and confirmation.

Configure the remote MCP tool with `defer_loading: true`. GPT-5.6 Luna supports
MCP and tool search, and deferred loading allows the model to load function
definitions only after it decides the server is relevant. Use `allowed_tools`
after authentication to import only the actor's eligible tools. Preserve the
returned `mcp_list_tools` item in the conversation/workflow context so tool
definitions are not re-imported every turn. This follows the current [OpenAI
MCP and Connectors guide](https://developers.openai.com/api/docs/guides/tools-connectors-mcp)
and [GPT-5.6 Luna model documentation](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

The allowlist is calculated from the freshly rehydrated actor, organization,
current channel, resource policy, feature flags, and service health. A tool
being visible does not authorize any particular record; record and field checks
still occur at execution.

### 4.2 Two-stage routing

1. **Capability discovery.** The model identifies the narrow business domain:
   knowledge, records, tasks/projects, calendar, people, analytics, or actions.
   It searches/loads only that domain's tools.
2. **Governed resolution.** The selected tool passes its compact business input
   to FastAPI. The executor resolves logical entities and authorized fields from
   server allowlists; it does not accept a database table, arbitrary field list,
   or SQL fragment from the model.

This reduces context pressure while making selection understandable. A route
classifier may bias discovery toward a domain, but it may never bypass MCP tool
schema validation or application authorization.

### 4.3 Call budget and routing rules

- Allow at most four read calls per user turn, with independent safe reads
  performed in parallel only when their combined scope is necessary.
- Allow one preview call per turn. Once a preview is returned, end the tool loop
  and present it to the user; do not issue a confirmation automatically.
- Do not fan out across domains unless the request explicitly needs the joined
  answer. Prefer one aggregate or server-side join over many record calls.
- Use `oyuns_records_aggregate` for counts and summaries. Use a pagination
  cursor instead of repeatedly widening limits.
- Treat `empty`, `denied`, `partial`, and `unavailable` as complete tool states.
  The model explains them safely and does not probe inaccessible references.

### 4.4 Catalog lifecycle

The edge publishes semantic catalog versions such as `2026-08-01.1` through its
initialize response and result envelope. A major version can change a schema or
remove a tool; a minor version only adds backward-compatible tools or fields.

The gateway caches eligible-tool lists by actor capability fingerprint and
catalog version for a short period. Role, account, organization, policy, or
feature-flag changes invalidate the fingerprint immediately. Catalog release
requires ambiguous-routing evaluations, tool-selection success measures,
latency/token budget measures, and authorization regression tests.

## 5. Payload optimization contract

### 5.1 Common result envelope

Every tool returns the same top-level shape. `data` is domain-specific but
always projected and bounded.

```json
{
  "status": "ok",
  "summary": "Found 2 authorized task blockers for the current week.",
  "data": {
    "items": []
  },
  "sources": [],
  "page": {
    "next_cursor": null,
    "returned": 0
  },
  "warnings": [],
  "request_id": "req_demo_01"
}
```

`status` is exactly one of `ok`, `empty`, `partial`, `denied`, or
`unavailable`. Internal primary keys, raw model metadata, tool-call IDs,
database errors, credentials, and storage keys are omitted. Where a follow-up
is appropriate, return an opaque actor-bound reference.

### 5.2 Server-side reduction rules

Before serialization, the executor applies, in this order:

1. organization predicate, actor capability/RBAC checks, and resource policy;
2. allowlisted field projection and classification-based field redaction;
3. parameterized input filters and deterministic ordering;
4. aggregate/grouping computation when the request asks for a summary;
5. pagination and output size controls;
6. citation/provenance attachment and safe text normalization.

Default and hard limits are:

| Resource | Default | Maximum |
| --- | --- | --- |
| Structured rows | 10 | 50 per page |
| Knowledge passages | 5 relevant passages | 5 passages per response |
| Tool result | 32 KB / about 8,000 tokens serialized | 32 KB / about 8,000 tokens serialized |
| Query text | 500 characters | 500 characters |
| Array filter | 10 values unless a schema declares a lower safe bound | 50 only for task participant IDs after authorization |

Knowledge passages contain title, concise relevant excerpt, classification-safe
locator, and opaque source reference. They do not contain the complete file,
raw binary data, or an unbounded document section. Retrieved documents are
untrusted reference data: strip active markup, do not follow instructions from
their content, and preserve provenance for the final answer.

### 5.3 Deterministic overflow behavior

If a permitted result exceeds the size budget, reduce it in this exact order:

1. remove unrequested optional fields;
2. shorten knowledge excerpts while retaining title and locator;
3. reduce rows while retaining deterministic order;
4. return `partial`, `OUTPUT_TRUNCATED`, a warning, and an opaque
   `next_cursor` where more permitted data exists.

Never silently truncate and never switch to raw data dumps. A user can request
the next page or a more focused aggregate.

### 5.4 Sensitive-data projection

The output policy redacts or excludes credentials, passwords, tokens, Telegram
IDs, attachment storage keys, private calendar details, free-text notes without
a specific approved projection, and fields above the actor's classification
ceiling. For calendar requests, callers without detail access receive only
free/busy timing. `restricted` resources require the existing explicit account
grant or administrator authority; an absence of access is indistinguishable
from a non-visible record.

## 6. Security and guardrails

### 6.1 Authorization and data classification

Access is deny-by-default. First authorize the actor, then the organization,
then the capability, then the resource/row, and finally fields in the response.
The existing classifications remain authoritative:

| Classification | MCP treatment |
| --- | --- |
| `public_link_safe` | Return only the approved metadata and a short-lived, allowlisted delivery link when policy allows |
| `internal` | Organization-readable after normal role/capability checks |
| `confidential` | Management or explicit role/team/project/account grant required |
| `restricted` | Administrator or explicit account grant required; never enumerate denied names |

The model receives only filtered results. It cannot widen a query by changing a
tool argument, ask the MCP edge to impersonate an account, or infer a denied
record from an error message.

### 6.2 Read, preview, and confirmation separation

Read and non-executing preview tools may use `require_approval: "never"` only
after the server declares the capability safe. Every confirmation or sensitive
action happens in the trusted channel and requires the user's explicit click.
This matches the guidance to require approval for sensitive MCP actions in the [OpenAI MCP safety
documentation](https://developers.openai.com/api/docs/guides/tools-connectors-mcp).

`oyuns_tasks_prepare_create` and `oyuns_tasks_prepare_update` create a
one-time preview with:

- action type, canonical validated payload, optional idempotency key, and
  expected source-record version;
- actor account, organization, channel, and capability fingerprint binding;
- a 10-minute expiration and unconsumed state; and
- a clear user-facing summary that distinguishes preview from completion.

The trusted confirmation handler receives only the opaque action reference. It
reloads the action and rechecks account status, organization, roles, capability,
channel, record visibility, expected version, expiry, idempotency, and replay
state inside one transaction. It records the execution outcome then marks the
action consumed. Confirm calls receive no automatic retry.

### 6.3 Rate limits and abuse controls

Start with the following defaults; make them organization-configurable without
raising any hard safety ceiling:

| Scope | Read | Preview | Confirm | Concurrency |
| --- | ---: | ---: | ---: | ---: |
| Per actor | 60/minute | 10/minute | 5/minute | 10 active reads |
| Per organization | 600/minute | policy-derived from actor limits | policy-derived from actor limits | 50 active reads |

Use an atomic distributed limiter keyed by organization and account. Apply
limits before expensive discovery or downstream calls. Return `RATE_LIMITED`
with a coarse `retry_after_seconds` in the safe result envelope; do not reveal
limiter backend, tenant traffic, or internal capacity.

### 6.4 Input, output, and prompt-injection controls

- Validate strict JSON Schema again in FastAPI, normalize Unicode, enforce
  length/range/date/cursor/reference bounds, and use only parameterized queries.
- Reject unknown fields, SQL fragments, control characters, unsafe URL schemes,
  unapproved outbound domains, raw table/column selectors, and forged opaque
  references.
- Allow outbound/download URLs only from a configured OYUNS allowlist, using
  HTTPS and short-lived signed links. Do not automatically fetch URLs found in
  retrieved content.
- Treat all retrieved content as data, not instruction. Delimit it in prompts,
  strip active markup, preserve source classification, and prevent it from
  changing system rules or tool permissions.
- Use structured, redacted audit events containing tool name, access decision,
  safe resource references, status, request ID, duration, and result size. Keep
  encrypted content separate from retained metadata.

### 6.5 Operational governance

Rotate JWT signing keys, mTLS certificates, and service secrets on a defined
schedule; immediately revoke sessions/certificates after suspected compromise.
Review access grants, tool call audit metadata, alert thresholds, and output
redaction samples periodically. Complete a data-residency and retention review
before enabling a remote MCP connection; data sent to any MCP service remains
subject to that service's controls.

## 7. Public MCP interface

### 7.1 Endpoint and headers

The production deployment publishes an environment-specific endpoint such as
`https://mcp.<approved-oyuns-domain>/mcp`; this document intentionally does not
name a production host. It supports Streamable HTTP only.

| Header | Requirement |
| --- | --- |
| `Authorization: Bearer <jwt>` | Required; short-lived, audience-bound OYUNS token |
| `MCP-Protocol-Version` | Required after initialization; server negotiates a supported version |
| `X-Request-Id` | Optional caller correlation ID; server validates or replaces it |
| `Idempotency-Key` | Required for preparation/confirmation requests as declared by the tool schema |
| `traceparent` | Optional trace context, subject to validation and sampling policy |

The initialize response declares the catalog version and supported protocol
versions. Unsupported major versions return `INVALID_INPUT` with supported
versions, not an internal stack trace. Tool schemas and error codes are
versioned public contracts; tables, models, routes, queues, and adapter APIs
are not.

### 7.2 Error codes

| Code | Meaning and safe response |
| --- | --- |
| `AUTH_REQUIRED` | Missing, expired, invalid, or audience-mismatched credentials |
| `ACCESS_DENIED` | Authenticated actor lacks a capability or record access; do not reveal restricted details |
| `INVALID_INPUT` | Schema, cursor, date, enum, or reference validation failed |
| `RATE_LIMITED` | Applicable rate or concurrency limit was reached; return retry metadata |
| `NOT_FOUND_OR_NOT_VISIBLE` | Resource does not exist in the authorized scope or is not visible |
| `STALE_ACTION` | Preview source version or authorization state changed before confirmation |
| `ACTION_EXPIRED` | Preview expired, was consumed, or was cancelled |
| `SOURCE_TIMEOUT` | Database or internal ERP dependency exceeded its deadline |
| `OUTPUT_TRUNCATED` | Permitted result was reduced to preserve the output budget; include cursor if applicable |

Map validation and policy errors to `denied` or `empty` when that avoids an
existence leak. Unexpected failures map to `unavailable` and a generic safe
summary; detailed diagnostics stay in protected logs and audit records.

### 7.3 Normative examples

All identifiers, times, hosts, and content below are illustrative.

**Knowledge search request**

```json
{
  "jsonrpc": "2.0",
  "id": "call-001",
  "method": "tools/call",
  "params": {
    "name": "oyuns_knowledge_search",
    "arguments": {
      "query": "annual leave approval process",
      "search_mode": "hybrid",
      "file_types": [],
      "limit": 5
    }
  }
}
```

**Knowledge search result**

```json
{
  "status": "ok",
  "summary": "Found 2 authorized knowledge passages about annual leave approval.",
  "data": {
    "items": [
      {
        "reference": "src_eyJvcmciOiJkZW1vIn0",
        "title": "Annual leave policy",
        "excerpt": "Submit the leave request before the planned absence and obtain manager approval.",
        "locator": "Policy section 3"
      }
    ]
  },
  "sources": [
    {
      "reference": "src_eyJvcmciOiJkZW1vIn0",
      "title": "Annual leave policy"
    }
  ],
  "page": {
    "next_cursor": null,
    "returned": 1
  },
  "warnings": [],
  "request_id": "req_demo_knowledge_01"
}
```

**ERP task query**

```json
{
  "jsonrpc": "2.0",
  "id": "call-002",
  "method": "tools/call",
  "params": {
    "name": "oyuns_tasks_search",
    "arguments": {
      "completion_state": "open",
      "workflow_status": "in_progress",
      "blockers_only": true,
      "active_only": false,
      "limit": 10
    }
  }
}
```

**Denied result**

```json
{
  "status": "denied",
  "summary": "You do not have access to that resource.",
  "data": {},
  "sources": [],
  "page": {
    "next_cursor": null,
    "returned": 0
  },
  "warnings": [
    "ACCESS_DENIED"
  ],
  "request_id": "req_demo_denied_01"
}
```

**Partial paginated result**

```json
{
  "status": "partial",
  "summary": "Returned the first 10 authorized tasks; more matching tasks are available.",
  "data": {
    "items": []
  },
  "sources": [],
  "page": {
    "next_cursor": "page_eyJvcmciOiJkZW1vIiwicGFnZSI6Mn0",
    "returned": 10
  },
  "warnings": [
    "OUTPUT_TRUNCATED"
  ],
  "request_id": "req_demo_page_01"
}
```

**Preview then confirmation**

```json
{
  "jsonrpc": "2.0",
  "id": "call-003",
  "method": "tools/call",
  "params": {
    "name": "oyuns_tasks_prepare_create",
    "arguments": {
      "title": "Review supplier proposal",
      "description": null,
      "assignee": "self",
      "reviewer": null,
      "priority": 2,
      "deadline_at": "2026-08-20T17:00:00+08:00",
      "project_ref": null
    }
  }
}
```

```json
{
  "status": "ok",
  "summary": "Task preview created. Ask the user to confirm it in the current channel.",
  "data": {
    "pending_action": {
      "action_reference": "mcpact_example",
      "action_type": "create_task",
      "expires_at": "2026-08-20T09:10:00Z",
      "title": "Review supplier proposal",
      "priority": 2,
      "deadline_at": "2026-08-20T17:00:00+08:00"
    }
  },
  "sources": [],
  "page": {
    "next_cursor": null,
    "returned": 1
  },
  "warnings": [],
  "request_id": "req_demo_preview_01"
}
```

The model cannot confirm this action. The Web/Telegram UI sends the opaque
reference to its existing trusted confirmation endpoint; the server resolves it
for the same actor, organization, and channel, then commits the transaction.
If the preview has expired, been consumed, changed under optimistic concurrency,
or is no longer authorized, it returns `ACTION_EXPIRED`, `STALE_ACTION`, or
`ACCESS_DENIED` without applying a change.

## 8. Verification and acceptance criteria

Before implementation, test the contract with mocked edge/executor boundaries
and the existing enterprise tool policy behavior.

- Correct tool selection for knowledge, directory, task/project, calendar, and
  metric requests; ambiguous requests load only the necessary tool domain.
- Large catalogs use deferred discovery and actor-scoped `allowed_tools`; tool
  list state is reused on a continuing conversation and invalidated on policy
  change.
- Tenant isolation holds for every search/get/aggregate path; restricted names,
  metadata, and existence are not disclosed to unentitled callers.
- Knowledge text containing instruction-like content cannot change tool routing,
  permissions, or output policy.
- Pagination, 32 KB overflow reduction, cursor tampering, summary aggregation,
  and `partial`/`OUTPUT_TRUNCATED` behavior are deterministic.
- Actor and organization limits, concurrency limits, downstream timeouts,
  circuit opening, and safe retry metadata follow this document.
- A stale role, expired/cancelled/replayed preview, duplicate idempotency key,
  changed source version, and a failed audit each follow their defined
  fail-closed behavior.
- Audit records contain redacted data and safe resource references; no test
  fixture, document, or log uses real credentials, production secret values, or
  private endpoints.

## 9. Implementation assumptions

- “ERP Platform” means OYUNS ERP capabilities already represented in this
  repository: tasks, projects, plans, calendars, people, reports, work time,
  files, and governed statistics.
- The first runtime release is a hybrid gateway: Streamable HTTP MCP edge plus
  mTLS delegation to FastAPI application services.
- All initial mutations use preview plus explicit confirmation. Direct mutation
  tools are prohibited.
- Existing OYUNS RBAC, resource policies, encrypted audit retention, pending
  action expiry, PostgreSQL persistence, and pgvector knowledge retrieval are
  authoritative.
- The runtime is present as `mcp-edge` plus the private `/v1/mcp-executor`
  route. It remains disabled until `AI_MCP_ENABLED=true`, an HTTPS
  `AI_MCP_SERVER_URL`, and an optional canary organization allowlist are set.

## 10. Deployment and canary runbook

1. Deploy the `mcp-edge` Compose service on its own HTTPS domain and point
   `AI_MCP_SERVER_URL` at `/mcp`. Do not route the backend executor publicly.
2. Generate a distinct `MCP_INTERNAL_SHARED_SECRET`, set it on both backend and
   edge, and configure the private mTLS proxy/cert paths before production
   enablement (`MCP_INTERNAL_REQUIRE_MTLS=true`).
3. Keep `AI_MCP_ENABLED=false` until the edge health check, migration, catalog
   tests, and tenant isolation checks pass. Enable it only with
   `AI_MCP_ORGANIZATION_ALLOWLIST=<canary-org-id>`.
4. Compare canary read and preview results with the direct tools. Monitor
   denied/partial/unavailable outcomes and redacted audit metadata. Do not
   enable new mutation paths: confirmation stays in Web/Telegram.
5. Roll back immediately by setting `AI_MCP_ENABLED=false`; the AI gateway
   resumes the existing direct FastAPI tool route without data migration.
