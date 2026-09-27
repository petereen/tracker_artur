# CRM module (Харилцагч + Харилцаа холбоо)

Built from Dayansoft ERP docs d026 “Харилцагч” (`docs/Dayansoft MD/30-…`) and d027 “CRM буюу харилцаа холбоо” (`docs/Dayansoft MD/31-…`), with statuses (d-Төлөв, `51-…`), meta (`50-…`) and payment terms (`40-…`). Note: the Dayansoft export's file names do not match their contents — read the `title:` front matter.

## Shape

| Layer | Where |
|---|---|
| Customer master | `erp_parties` (extended, not a new table). Legacy `clients` (PSA) is untouched and still linked via `erp_parties.legacy_client_id`. |
| Reference data | `erp_party_groups`, `erp_payment_terms`, `erp_party_contacts`, `erp_party_bank_accounts`, `erp_statuses` (generic per-register statuses; CRM uses `register='crm_activity'`), `crm_activity_types` — `app/models/crm.py` |
| Activity log | `crm_activities` — party optional (internal work allowed), contact snapshot, due/overdue, responsible, links to contract / project / task, close + review, expected revenue |
| API | `app/crm/` mounted inside the ERP router at `/v1/erp/crm` (`parties.py`, `activities.py`, `settings.py`) |
| Tax lookup | `app/services/ebarimt_lookup.py` (РД → ТТД → name, НӨАТ/НХАТ). Failures always fall back to manual entry. |
| Reminders | `app/services/crm_reminders.py`: due-soon, overdue (owner) and escalation (owner's `manager_id`, after `overdue_escalation_days` working days); job every 15 min in the bot scheduler. CRM items also appear in the employee morning digest. |
| UI | `/erp/crm` (activities), `/erp/crm/customers[/:partyId]`, `/erp/crm/settings` — `frontend/src/pages/CRMWorkspacePage.tsx`, `frontend/src/components/crm/*`, `frontend/src/api/crm.ts` |
| Migration | `d1e2f3a4b5c6_crm_module` (after `c0d1e2f3a4b5`): backfills buyer/supplier flags from `party_type`, copies legacy JSON contacts into `erp_party_contacts`, grants CRM capabilities to existing `erp_sales` roles. |

## Rules worth knowing

- **Authorization** is the ERP capability model: resources `parties`, `crm_activity`, `crm_settings`. Admins pass; `manager`/`team_lead` get view/create/edit through the existing bridge; everyone else needs an ERP role such as the seeded **Sales** (`erp_sales`). Delete needs `archive`. The nav item and routes follow `GET /v1/erp/crm/capabilities`, not system roles, so sales staff without a management role can use CRM.
- **Module toggle** (`crm` in Modules & Features) only controls nav visibility, like other ERP modules; it does not disable the API.
- **Party code** auto-numbers from `10001` (5 digits, sequence `crm_party_code`), skipping manually used codes.
- **Duplicate TIN/РД** returns `409 crm_party_duplicate_tin` unless `confirm_duplicate_tin=true` (branches may share a TIN). Duplicate names are warnings only. Lists flag both.
- **Delete vs deactivate**: a party with documents, activities, child parties or price lists returns `409 crm_party_in_use`; deactivate it instead (`inactive_since` is stamped).
- **Statuses are manual** (as in Dayansoft). The fixed `category` (`open|in_progress|waiting|done|cancelled`) drives open/overdue logic. Choosing a `done`/`cancelled` status or ticking “Хаагдсан” fills `completed_at` if empty.
- **Overdue days** = (completed date, or today while open) − due date, never negative.
- **Change log** (Лог) is `audit_logs` rows with `entity_type='erp_party'`; tracked fields are `PARTY_TRACKED_FIELDS` in `app/crm/service.py`.
- **Follow-up tasks**: “Даалгавар үүсгэх” creates a real `tasks` row linked via `crm_activities.task_id`, so the task board's reminders apply. It respects `actor_can_assign_tasks`.
- **Optimistic locking**: PATCH accepts `version`; stale writes get `409 crm_version_conflict`.

## Tests

- `backend/tests/test_crm_contract.py` — pure rules, schemas, route order, e-Barimt parsing (no DB).
- `backend/tests/test_crm_db.py` — end-to-end against PostgreSQL; runs only with `CRM_TEST_DATABASE_URL=postgresql+asyncpg://…/throwaway_db`.
- `frontend/src/pages/CRMWorkspacePage.test.tsx`.

## Not built (deliberately)

Deal pipeline with stages / lead → quotation handoff (Dayansoft has none; the generic `lead`/`opportunity` ERP documents remain), buy/sell item lists per party (depend on the gated Selling/Buying phase), per-user “own records only” restriction, assistant/bot CRM tools.
