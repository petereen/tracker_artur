# Production hardening runbook

The supported production shape is Docker Compose on Dokploy with PostgreSQL as the system of record, a dedicated worker, a single Telegram polling process, and one or more API replicas. Local attachments must remain on the private mounted volume shared by API and worker services.

## Before deployment

1. Create an off-host PostgreSQL backup and verify its checksum and retention policy.
2. Restore that backup into an isolated database and run `alembic upgrade head` there.
3. Run `ops/hardening-exercises.sh validate`, `migration`, `backup-restore`, `load`, `notification-burst`, and `worker-recovery` with `.env` set to non-production infrastructure.
4. Run frontend unit/build checks and `npm run test:e2e` after installing Playwright Chromium.
5. Confirm `/health`, authenticated API calls, WebSocket replay from the last cursor, worker leases, Telegram deduplication, and ClamAV failure behavior.

## Google Calendar push setup

- Set `GOOGLE_WEBHOOK_URL=https://erp.oyuns.mn/api/v1/integrations/google-calendar/webhook`; it must be publicly reachable over valid HTTPS.
- OAuth completion queues creation of a seven-day Google watch. The worker renews channels expiring within 24 hours.
- Webhooks are accepted only when channel ID, resource ID, encrypted channel token, expiration, and monotonically increasing message number validate.
- `outbound` is the default. In `bidirectional` mode Google may update linked task start/end timestamps only. Google deletion removes the link and never deletes the OYUNS task.
- A `410 Gone` sync cursor triggers one bounded 30-day resync. Repeated failures remain in `job_queue`, increment connection failure metadata, and appear in integration settings.

## Failure and rollback

- Provider outage: leave task/report/clock operations enabled, inspect failed leased jobs, and retry after provider recovery.
- Worker outage: restart the worker; expired leases are reclaimed and deduplication keys prevent duplicate delivery.
- API replica outage: remove the unhealthy replica; durable events allow clients to reconnect from their cursor.
- Migration rollback: restore the verified pre-migration backup if an additive migration cannot be corrected forward. Do not downgrade a live database after new application writes have occurred.
- Calendar disconnect: the channel is stopped best-effort and the local connection/link rows are removed without touching tasks.

Record timestamps, image revisions, migration head, test output, backup checksum, restore result, p95 latency, and operator sign-off in the deployment ticket. Live production execution remains an operator-authorized action.

## Local implementation evidence (2026-08-10)

- An isolated PostgreSQL 15 volume upgraded to Alembic head `b1c2d3e4f5g6`; the resulting schema contained 68 public tables and the new Calendar connection columns.
- A logical backup restored into a second isolated database with the same migration head and table count.
- PostgreSQL event replay ordering and job deduplication tests passed, as did the focused Google webhook/RBAC suite.
- Frontend unit tests, production TypeScript/Vite build, and desktop/mobile Playwright checks passed.
- The complete backend baseline currently reports 245 passing and 13 failing tests. The failures are in pre-existing assistant/bot mock expectations, foundation serialization/migration expectations, exchange-rate/digest mocks, and work-time aggregation; they are not hidden by the phase-specific suite.
- Live Google credentials, production notification providers, destructive rollback, sustained load, and operator outage drills were not invoked locally. Use the commands above in an authorized rehearsal environment and attach their measurements to the deployment ticket.
