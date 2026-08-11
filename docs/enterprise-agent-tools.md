# Enterprise Agent Tools

The enterprise OYUNS tool layer is enabled with `ENTERPRISE_TOOLS_ENABLED=true`.
It uses the Responses API with `store:false`; application-owned web and Telegram
conversation records remain the source of history.

## Tools

| Tool | Purpose | Key limits |
| --- | --- | --- |
| `file_search_tool` | Hybrid search over indexed company files and knowledge | 1–10 results; citations include a document locator |
| `get_stats_tool` | ERP task, work-time, report, project, and budget metrics | Revenue, DAU, and support metrics are rejected as unsupported |
| `project_mgmt_tool` | Scoped projects, tasks, blockers, and milestones | Milestones are the v1 sprint-like view |
| `project_mgmt_update_tool` | Generates a task update preview only | One-time actor/channel-bound confirmation expires in 10 minutes |
| `calendar_tool` | Events, schedule, and availability | Private details follow role hierarchy; others see free/busy |

All input schemas are strict and inject actor/organization server-side. Every
result includes `ok`, `empty`, `partial`, `denied`, or `unavailable`, plus safe
sources, delivery actions, and warnings.

## Access and delivery

- `public_link_safe` resources may use short-lived signed downloads.
- `internal` resources are organization-readable and may be sent directly in Telegram.
- `confidential` resources require management or explicit role/team/project/account grants.
- `restricted` resources require admin or explicit account grants.

Policies inherit from parent folders. Existing company files and unambiguous
legacy knowledge records are backfilled as `internal`. Content is filtered
before both retrieval and model calls; source IDs are opaque and database,
Telegram, credential, and rate-internal fields are omitted.

## Indexing and operations

Company-file uploads enqueue `knowledge_index_file`. Supported extractors are
PDF, DOCX, XLSX, PPTX, TXT, Markdown, and CSV. Chunks are bounded to 800 words
with a 120-word overlap and embed through the configurable
`OPENAI_EMBEDDING_MODEL` (default `text-embedding-3-small`). Search degrades to
keyword ranking when embeddings are unavailable.

Deploy `pgvector/pgvector:pg15`, run `alembic upgrade head`, then run:

```bash
cd backend
python scripts/verify_enterprise_tools.py
```

Tool prompts/results are encrypted for 30 days; metadata remains for 365 days.
The worker creates an `assistant_audit_purge` job daily. Conversations remain
until their owner deletes them.
