# Production provider configuration

Copy `.env.example` into the deployment secret manager. Never commit populated
credentials. Keep `SECRET_KEY` stable after launch because refresh sessions,
queued authentication links, and Google credentials depend on it.

## 1. Optional Resend authentication email

The current deployment intentionally uses the predefined admin username and
password from the admin panel. Email verification, invitation links, and email
password resets are disabled by default. Keep this section disabled until you
explicitly set `AUTH_EMAIL_VERIFICATION_ENABLED=true`.

1. Add the company sending domain in Resend and publish the DNS records Resend
   provides. Wait until the domain shows as verified.
2. Create a domain-restricted **Sending access** API key. Full account access is
   not required.
3. Use a sender address on that verified domain and configure:

```env
PUBLIC_APP_URL=https://erp.oyuns.mn
CORS_ORIGINS=https://erp.oyuns.mn
AUTH_EMAIL_VERIFICATION_ENABLED=false
ADMIN_USERNAME=admin
ADMIN_PASSWORD=replace-on-first-login
SMTP_HOST=smtp.resend.com
SMTP_PORT=465
SMTP_USERNAME=resend
SMTP_PASSWORD=re_your_sending_only_key
SMTP_FROM=OYUNS Workspace <auth@example.com>
```

Port `465` uses implicit TLS. If the hosting provider blocks it, use port `587`;
the application will use STARTTLS. The `worker` service must receive the same
SMTP and `SECRET_KEY` values as the API service. This is optional in the current
username/password-only rollout.

## 2. Google Calendar

1. Create or select a Google Cloud project and enable **Google Calendar API**.
2. Configure the OAuth consent screen. For one Google Workspace company, choose
   Internal where the Workspace account permits it.
3. Create an OAuth client of type **Web application**.
4. Add this exact authorized redirect URI, including `/api`:
   `https://erp.oyuns.mn/api/v1/integrations/google-calendar/callback`.
5. Configure the API and worker services:

```env
GOOGLE_CLIENT_ID=your-client.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=https://erp.oyuns.mn/api/v1/integrations/google-calendar/callback
```

Restart the API and worker, sign in, open Administration, and choose **Google
Calendar → Connect**. The application requests only `calendar.events` with
offline access, encrypts access/refresh tokens, and queues outbound task-event
synchronization. The existing prefilled Calendar URL remains available if OAuth
is not configured.

Inbound Calendar push webhooks and bidirectional scheduling changes remain a
separate rollout item; do not advertise bidirectional synchronization yet.

## 3. Private attachments on the VPS

No Azure configuration is required. Dokploy mounts the private
`attachment_uploads` volume into the API container. Keep
`ATTACHMENT_STORAGE_BACKEND=local`; downloads still pass through application
authorization, executable file types are blocked, and SHA-256 checksums are
stored. Back up the Docker volume with PostgreSQL.

## 4. Existing optional providers

```env
BOT_TOKEN=Telegram bot token
TELEGRAM_BOT_USERNAME=Telegram bot username without @ (enables browser Login Widget)
MINI_APP_URL=https://erp.oyuns.mn/tg
TELEGRAM_REFRESH_TOKEN_DAYS=365
OPENAI_API_KEY=OpenAI project key
CHIMEGE_API_TOKEN=Chimege STT token
CHIMEGE_TTS_API_TOKEN=Chimege TTS token
AGENT_RATES_API_KEY=OYUNS rates service key
```

Opening the Mini App verifies Telegram's signed `initData`, links the active
registered employee to an enterprise account, and writes a one-year `HttpOnly`
browser session. It is revoked only by Logout (or account disablement); clearing
browser/Telegram storage also removes the local cookie. Add each employee's
Telegram ID in Administration before they use this sign-in.

Manual tasks, reports, and the Calendar URL fallback remain available when AI,
voice, rates, or Calendar providers are unavailable.

For browser Telegram login, set `TELEGRAM_BOT_USERNAME` and use BotFather's
`/setdomain` command with `erp.oyuns.mn`, then rebuild the frontend so the Login
Widget is included. The Mini App itself does not require the Login Widget.

## 5. Deployment order

1. Back up PostgreSQL.
2. Deploy the new image and run `alembic upgrade head` once (current head: `x2y3z4a5b6c7`).
3. Start `clamav`, then `backend`, `worker`, `bot`, and `frontend`; verify `/api/health` and one clean test upload.
4. Test admin login, create a second account from Administration, change its
   password/status, private attachment access, Google connection, and one task
   sync with a pilot account.
5. Review failed `job_queue` records and provider dashboards before broad rollout.
# Malware scanning and profile avatars

Production compose deployments run the official `clamav/clamav:1.4` LTS image and set `CLAMAV_ENABLED=true`. Attachment and avatar uploads fail closed with HTTP 503 while the scanner is unavailable, and infected files are rejected before storage. Custom avatars use the persistent `avatar_uploads` volume, accept PNG/JPEG/WebP up to 2 MB, and reject dimensions over 256×256 pixels. Budget roughly 4 GB of RAM for the ClamAV service and persist `/var/lib/clamav` so signature updates survive restarts.
# Google Calendar inbound synchronization

Set `GOOGLE_WEBHOOK_URL` to the public HTTPS webhook at `/api/v1/integrations/google-calendar/webhook`. OAuth queues channel registration automatically. Keep the worker running so watches renew before expiration and incremental events are processed. Outbound mode remains the default; enable bidirectional mode per account only when Google schedule changes should update linked OYUNS task dates.
