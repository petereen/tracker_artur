# OYUNS AI assistant prompt and error contract

## Runtime architecture

Telegram and Web Chat use the same pipeline:

1. The application authenticates the actor and organization.
2. The application retrieves permission-scoped grounding context.
3. The gateway classifies the complete message, including all statements.
4. The gateway sends the same strict enterprise tool contract to the live model.
5. Tool execution remains in the application, where ACL checks, validation,
   audit records, and confirmation rules are enforced.
6. The model receives structured tool results and writes the final answer in the
   user’s language.

The model is never the authority for organization scope, access, IDs, mutation
approval, or whether an action succeeded.

## System instruction

The canonical runtime instruction is `ANSWER_SYSTEM` in
`backend/app/services/ai_gateway/gateway.py`. Its contract is:

- Read the complete message before choosing a route; preserve context from
  multi-statement messages.
- Separate retrieval from action intents. Retrieve first when context is needed
  to form an action.
- Use `file_search_tool` with `operation=list` for directory/list requests and
  `operation=search` for content or semantic search.
- Put all user-provided task context into the title/description, resolve only
  authorized people, and use timezone-aware ISO-8601 deadlines.
- Ask one focused clarification question when a required value is genuinely
  ambiguous or absent. Never invent dates, people, permissions, or records.
- Treat `empty`, `denied`, `partial`, and `unavailable` as normal tool states,
  not as model/API failures.
- Show a preview for mutations and wait for explicit confirmation. A read-only
  calendar operation never creates a meeting or reminder.
- Never expose internal IDs, action tokens, raw JSON, credentials, hidden
  fields, or retrieval metadata.

## Tool schema contract

Every function is sent with `strict: true`. Every object property is included in
`required`; optional values are represented as nullable values. The application
normalizes Pydantic schemas recursively, including nested definitions, before
sending them to OpenAI. The application then validates the returned arguments
again before execution.

## Error-handling contract

Tool failures are returned to the model as structured results:

- `empty`: no authorized match; explain that nothing matching was found.
- `denied`: do not disclose restricted details; explain the access or parameter
  issue and ask for a permitted alternative if useful.
- `partial`: state what was completed and what remains unavailable.
- `unavailable`: state the affected capability, say whether an action occurred,
  and offer retry or clarification. Never imply a mutation succeeded.

Malformed model arguments are converted into a structured clarification result.
Unexpected tool exceptions are logged with the tool name and converted into an
`unavailable` result. They must not abort the Telegram or Web conversation.

Provider/API failures are logged with the provider body and request stage. The
channel adapter may localize a short retry message, but it must not fabricate a
business answer or claim that a task, meeting, reminder, or file operation was
completed.

## Verification checklist

Test both channels against generic classes, not only individual examples:

- simple conversational question;
- file directory listing;
- file content search with a file-type filter;
- multi-sentence task/delegation request;
- meeting/reminder request when only read-only calendar tools exist;
- missing assignee or timezone;
- denied file and employee access;
- empty retrieval result;
- simulated tool timeout/exception;
- malformed function arguments;
- explicit task confirmation and repeated confirmation.

The OpenAI strict function-calling requirements are documented in the
[official function-calling guide](https://developers.openai.com/api/docs/guides/function-calling).
