
# Mobile app plan: biometrics, native push, automatic geofence worktime

Status: **plan, not implemented** (2026-10-02). Approach chosen: **Capacitor shell + OTA for the web layer + thin native plugins**, in this repo. Companion to [`mobile-release.md`](mobile-release.md) (build/OTA/push runbook).

Decisions already made:
- Same repo (`frontend/` holds the Capacitor projects; `backend/` holds API, OTA server, push delivery).
- **Fully automatic** clock-in and clock-out (no confirm push). Employee must accept a disclaimer that the company processes their location data.

## 1. What exists vs. what is missing

| Area | Exists | Gap |
|---|---|---|
| Shell, OTA, rollback | Capacitor 8, `@capgo/capacitor-updater` + self-hosted `/v1/mobile-updates`, `ota:*` scripts | CI does not publish OTA; no native-capability gating |
| Native push | `@capacitor/push-notifications`, `PUT /v1/mobile/push-registration`, FCM/APNs sender | Only `chat_push` jobs use it; tasks/reports/worktime/etc. do not |
| Session storage | Keychain/Keystore refresh token (`platform/secure-session.ts`) | No biometric gate |
| Worktime | `POST /v1/enterprise/clock/start` with one-point org geofence (`worktime_geofence.py`), manual button (`WorkdayStartButton.tsx`), QR, `WorkTimeEntry.source_channel`/`work_location_id` columns | No background detection, one site only, no event log, no consent record |
| Custom native code | `AudioRoutePlugin` (Swift + Java) as the pattern to copy | No location/biometric plugin |

## 2. OTA vs. binary boundary

Everything below the line needs a **store/TestFlight binary once**; everything above ships by OTA afterwards.

OTA (web layer): consent screens, onboarding, settings UI, profile cards, biometric lock logic, rules UI, i18n, bug fixes in JS, all backend changes.

Binary (native): geofence plugin, biometric plugin, `Info.plist` keys (`NSLocationAlwaysAndWhenInUseUsageDescription`, `NSLocationWhenInUseUsageDescription`, `NSFaceIDUsageDescription`, `UIBackgroundModes`: `location`, `remote-notification`), Android permissions (`ACCESS_FINE_LOCATION`, `ACCESS_BACKGROUND_LOCATION`, `USE_BIOMETRIC`, `RECEIVE_BOOT_COMPLETED`), receivers, entitlements, Firebase/APNs config.

Rules to keep native changes rare:
1. Native layer only **registers regions and reports transitions**. All decisions (start, stop, grace, schedule, anti-spoofing) live on the server.
2. Plugins expose a version: `getNativeCapabilities() -> { geofence: 1, biometric: 1 }`. JS feature-detects; an OTA bundle running on an older binary hides the feature instead of throwing.
3. Add `min_native_version` to OTA bundle metadata so a bundle that needs a newer binary is not delivered to old ones.
4. **Put every native permission and Info.plist/Manifest key into the first binary**, even for features shipped later.

## 3. Automatic geofence worktime

### 3.1 Flow

```
Admin enables auto mode + acknowledges employer disclaimer  (org setting, audited)
Employee opens app → sees disclaimer → accepts (biometric/password re-auth) → consent row stored
App enrolls device → server returns device credential (stored in Keychain/Keystore, native-readable)
App fetches sites → native plugin registers OS regions
OS wakes app on ENTER/EXIT → native POSTs event with device credential (JS may not be running)
Server: validate → rules engine → start/stop WorkTimeEntry (source_channel='geofence') → audit → informational push
Reconciliation: app-open + periodic state snapshot + end-of-day sweeper close gaps
```

### 3.2 Backend (new migration after head `5b7f1d3e9c26`; update `tests/test_alembic_graph.py`)

All tables carry `organization_id` + RLS policy (see `docs/multi-tenancy.md`) and are added to the ORM tenant guard.

- `worktime_sites`: org, `public_id`, name, lat, lng, `radius_meters`, `is_active`, optional schedule window. Migrate the existing single `organization.settings["worktime_geofence"]` into the first site; keep the old endpoints working as a facade until the web UI moves.
- `worktime_location_consents`: account, org, `policy_version`, `text_sha256`, `locale`, `accepted_at`, `revoked_at`, `app_platform`, `app_version`. Append-only; a re-acceptance is a new row.
- `mobile_devices`: account, org, platform, `credential_hash` (SHA-256 of a 256-bit random token, only the hash is stored), `consent_id`, `geofence_enabled`, OS permission snapshot (`always|when_in_use|denied`, `precise|approximate`), `last_event_at`, `last_state_at`, `revoked_at`. Device credential is **scoped to the geo endpoints only** and revocable; never hand the refresh token to native code.
- `worktime_geo_events`: device, site, `client_event_id` (UUID, unique per device → idempotency), `kind` (`enter|exit|state_inside|state_outside`), `occurred_at` (device) vs `received_at`, accuracy, `is_mock`, `result` (`started|stopped|ignored:<reason>|shadow`), `time_entry_id`. Retention job (default 90 days, org-configurable) alongside the existing purge jobs in `worker.py`.
- Org settings `worktime_methods` gains `auto_geofence_mode: off | shadow | on`, `exit_grace_minutes` (default 10), `min_accuracy_meters` (default 100), `employer_disclaimer_ack` (who/when/policy version), `geo_retention_days`.

Endpoints (`routers/mobile.py` or a new `routers/worktime_geo.py`; add the prefix to `FEATURE_ROUTES` if gated):
- `GET /v1/worktime/auto/consent-text`, `POST /v1/worktime/auto/consent`, `DELETE /v1/worktime/auto/consent` (revoke → revoke devices, stop regions).
- `POST /v1/mobile/devices` (enroll, requires valid consent) / `DELETE` (revoke).
- `GET /v1/mobile/geofences` (active sites for this device, ≤ 20 for iOS).
- `POST /v1/mobile/geo-events` (device-credential auth; batch accepted; idempotent).
- Admin: CRUD sites, auto-mode settings, events/“needs review” list (admin/hr only, `record_change` on reads of other people's location events).


## Risks worth knowing now
- Wrong pay: missed or late geofence events could produce wrong hours, which is why shadow mode, snapshots, and manager approval are in the plan.
- Store review: both stores scrutinise "always" background location. A clear disclosure, a QR fallback, and an accurate declaration are what get it through.
- Employee consent: consent from an employee is often not treated as freely given. The company should also cover this in its labour policy, and refusing must not be penalised. The app keeps QR and manual start as alternatives. This is a recommendation, not legal advice.
- Android battery managers: Xiaomi, Huawei, Oppo and Samsung kill background work and must be tested on real phones.
## Decisions I need from you
- When an employee exits, should it always stop the clock (my default), or count as a break during a lunch window? answer: stop the clock
- Are these defaults OK: 10-minute exit grace, 90-day retention of location events, 100 m accuracy threshold? answer: yes.
- Should the native plugin be a thin custom one (my pick: no license, little native code) or a commercial geolocation plugin (more proven on Android battery killers, paid license for Android release builds)? - 
- Who can see location events? My plan is admin and HR only, with managers seeing just the resulting time entries.
- Can an employee refuse automatic tracking and fall back to QR/manual (my plan), or is it mandatory by role?