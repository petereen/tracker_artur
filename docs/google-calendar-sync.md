# Google Calendar synchronization

The Calendar workspace connects one Google account per platform account. The
integration uses Google OAuth with offline access and the `calendar.events`,
`calendar.readonly`, `openid`, and `email` scopes.

Required environment values:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`, normally `https://erp.oyuns.mn/api/v1/integrations/google-calendar/callback`
- `GOOGLE_WEBHOOK_URL`, a public HTTPS URL ending in `/api/v1/integrations/google-calendar/webhook`

The callback is a GET route because Google redirects the browser to it. It
validates the one-time signed state and PKCE verifier, then returns a small
same-origin popup completion page. The canonical JSON exchange route is
`POST /api/v1/integrations/google-calendar/callback`.

Credentials and webhook channel tokens are encrypted with the application
secret. Access tokens refresh automatically shortly before expiry. Google
changes are received through a watch channel and reconciled with an
incremental `syncToken`; a 410 response resets the cursor and performs a
bounded recovery pull.

Platform tasks and private Calendar entries carry private Google extended properties
with their platform identity and fingerprint. Platform changes enqueue worker
jobs only for the relevant user’s connection: private Calendar entries go to
their owner, while tasks go only to connected users who are the creator, owner,
contributor, or reviewer. Company events, unrelated users’ tasks, and
unassigned tasks are not exported. Mapped Google changes are treated as
conflicts and the platform version is written back, preventing update loops.
New Google events are imported as private Calendar entries and then become
platform-controlled for that connected user.
