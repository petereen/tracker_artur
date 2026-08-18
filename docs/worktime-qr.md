# Dynamic Worktime QR

The office display is served at `/worktimeqr` and must be provisioned before it
can mint QR tokens. An administrator or manager creates a kiosk under
Administration → Check-in settings, opens `/worktimeqr` on the TV, and enters
the one-time eight-character pairing code. The code expires after ten minutes;
the resulting Secure, HttpOnly kiosk cookie lasts 180 days and can be revoked
from the same settings panel.

Set `WORKTIME_QR_SIGNING_SECRET` to an independently generated secret in
production. If it is rotated, existing QR codes stop working within the
configured 15-second grace period; displays must fetch a fresh token. The
display and employee scanner both require HTTPS for secure cookies and camera
access. Redis is used for pairing/scan rate limits through
`WORKTIME_QR_REDIS_URL`; the clock replay record remains in PostgreSQL so a
retry cannot toggle a shift twice across multiple API instances.

The QR expires after 30 seconds and is accepted for a further 15-second grace
window. It proves possession of the current office display code, not physical
presence against live video relaying; GPS and biometric checks are deliberately
outside this milestone. Existing Telegram commands and web clock controls
continue to operate on the same work-time entries.

When `TELEGRAM_BOT_USERNAME` is configured and the bot's Main Mini App points
to `/tg`, the displayed QR is also a Telegram Mini App deep link. Scanning it
with a phone camera opens Telegram, authenticates the employee with Telegram's
signed `initData`, and submits the short-lived QR token to the same idempotent
clock endpoint automatically. If the Telegram username is not configured, the
QR remains a normal OYUNS scanner token. Telegram may still show its standard
Mini App open confirmation.
