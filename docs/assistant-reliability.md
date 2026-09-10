# Assistant task reliability

The Web API and Telegram bot share the task gateway but run as separate
services. Rebuild and redeploy both `backend` and `bot` in Dokploy after this
change. These fixes add no database columns; the existing migration chain
must still have completed successfully.

## Expected behavior

Send `би маргааш 16 цагаас хуралтай шүү даалгавар үүсгэ` in each channel.
The preview should show tomorrow at 16:00 in the employee's timezone, with
no invented end time. Confirm once, then inspect the task's start field on
the platform. Repeating the same confirmation must use the existing action
replay behavior rather than create another task.

This standalone self-meeting request bypasses model classification, knowledge
retrieval, and AI generation. Requests with named participants, extra actions,
or ambiguous wording continue through AI. For a single recognizable date/time,
the server restores the supplied time if the model omits or misinterprets it.
Multiple dates and ranges remain model-resolved. Task previews are rendered
from the validated stored fields without an additional model request.
ISO dates and weekday-only requests are also recovered. Date-only values use
midnight in the employee's timezone rather than inheriting the request's clock
time; multiple AM/PM times are preserved for range resolution.

Telegram sends the signed token directly as callback data. The new `ap2`
format fits the 64-byte limit for the database's integer action IDs, including
the maximum integer value. Existing `ap1` tokens and prefixed callbacks remain
accepted. Signature checks still bind the action to its account, organization,
channel, payload, and expiry.

## Validation and diagnosis

`backend/requirements-test.txt` includes the dependencies for the focused
regression tests. Tests cover callback size and delivery, token compatibility
and actor binding, parsing, fast-path dependency avoidance, model time omissions,
confirmation fields, tool timeout recovery, and real AsyncSession/SQLite
conversation rollback behavior. They do not contact production, Telegram, or
the AI provider.

`test_assistant_postgres.py` additionally exercises real PostgreSQL task,
conversation, audit, and notification tables, then reloads and replays the
confirmation. Set `OYUNS_TEST_DATABASE_URL` to an isolated PostgreSQL database
to run it. It creates a unique temporary schema and removes that schema after
the test. Both channel cases passed against a local PostgreSQL 16 instance;
the remaining 75 focused regression cases also passed. This does not validate
the production migration state or the live Telegram/provider connections.

After deployment, if Telegram still reports an outage, inspect the bot log's
`assistant.telegram_route_failed` traceback; the browser's HTTP 500 stack cannot
identify a server exception. Preview storage failures are logged separately as
`ai_gateway.task_preview_failed`. Check for `BUTTON_DATA_INVALID`, database
migration errors, and the deployed revision before attributing the error to
the AI provider. Do not share tokens or credentials from logs.
