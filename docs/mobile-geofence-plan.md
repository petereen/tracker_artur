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

Device-credential auth has to resolve tenant from the credential hash (system-context lookup, then `tenant_scope`), because the tenant middleware normally derives it from host/JWT. Design this explicitly and test it under the non-superuser role (`test_multi_tenant_db.py` style).

Rules engine (`services/worktime_auto.py`, pure function + thin DB wrapper, unit-testable):
- **Enter** at an active site, inside the site's schedule window, accuracy ≤ threshold, not mock, device consented → if no active `in_person` work entry, start one at `occurred_at` (backdate capped, e.g. 15 min). Never interrupt a manual `remote` entry or any manual entry.
- **Exit** → schedule delayed job `geo_exit_finalize` (dedup key per employee/site). Re-enter within grace cancels it. Otherwise close the active in-person entry at the exit's `occurred_at`. Exits only close entries that started in-person at that site.
- Multiple entries per day are already supported (`WorkTimeEntry`), so lunch outside = stop + new start.
- **Reconciliation:** `state_*` snapshots (sent on app open, on iOS `requestState`, on significant location change) correct missed events. End-of-day sweeper closes stale geofence entries at the last known-inside time and marks `needs_review`.
- **Anti-spoof (best effort):** Android mock-location flag, accuracy gate, impossible-travel check (distance/time between events), per-device credential, optional Play Integrity / App Attest later. Cannot be fully prevented; QR remains the audit fallback. Flag anomalies to HR rather than silently trusting.
- Entries keep `approval_status='pending'`; manager can edit through the existing flow. Because these hours feed attendance and monthly payroll (`sync_worktime_attendance`, `day_lines`), every auto action writes `record_change` and an informational push to the employee ("Ажил эхэллээ 09:02 · Оффис").
- Raise the minimum configurable radius for auto mode to ≥ 100 m (today's minimum of 25 m is below what iOS/Android geofencing resolves reliably).

### 3.3 Shadow mode (safety net before payroll impact)

`auto_geofence_mode = shadow`: events are stored and the rules engine runs, but no `WorkTimeEntry` is written; results are logged as `shadow`. Compare against manual/QR entries in a report for 2–3 weeks, tune radius/grace, then switch to `on`. Fully-automatic is only enabled after the pilot matches reality.

### 3.4 Native plugin `OyunsGeofence` (Capacitor, pattern = `AudioRoutePlugin`)

JS API: `getCapabilities()`, `getPermissionStatus()`, `requestPermissions()` (staged), `start({ sites, apiBase, credential })`, `stop()`, `requestState()`, `getStatus()`.

- **iOS (Swift):** `CLLocationManager` region monitoring (`startMonitoring(for: CLCircularRegion)`), delegate `didEnterRegion` / `didExitRegion` / `didDetermineState`; staged permission (When-In-Use → Always); detect `accuracyAuthorization == .reducedAccuracy` and prompt for Precise; ≤ 20 regions; relaunch-on-region-event works after force-quit; post with `URLSession` inside `beginBackgroundTask`, persist unsent events and retry.
- **Android (Java/Kotlin):** `GeofencingClient` with `INITIAL_TRIGGER_ENTER|EXIT` and loitering delay, `PendingIntent` → `BroadcastReceiver` → `WorkManager` job (network constraint, backoff) that POSTs; re-register on `BOOT_COMPLETED` and `MY_PACKAGE_REPLACED`; separate background-location permission step on Android 11+; surface battery-optimization/autostart guidance for Samsung/Xiaomi/Huawei/Oppo.
- Credential storage native-readable: iOS Keychain (`afterFirstUnlock`, because events can fire before first unlock after reboot), Android Keystore-backed encrypted prefs.
- **Decision to confirm:** custom thin plugin (recommended: no license, native stays tiny because the server owns the rules) vs. a commercial background-geolocation plugin (more battle-tested on OEM battery killers, paid license for Android release builds, vendor lock-in). Plan: build the thin plugin, run the device test matrix in Phase 4, fall back to the vendor plugin only if reliability misses target.

### 3.5 Consent and disclaimer

Two acknowledgements, both versioned, timestamped and audited:
1. **Company (admin) enabling auto mode:** disclaimer that the company is collecting employees' location transitions for working-time tracking, that it must inform employees, keep a lawful basis, limit retention, and restrict access. Stored in `employer_disclaimer_ack`.
2. **Employee, before any permission prompt or region registration:** full-screen disclosure (this also satisfies Google Play's *prominent disclosure* requirement and Apple's purpose-string expectations): what is collected (enter/exit of company sites + timestamps, not a continuous route), when (also in background), why (automatic clock-in/out), who sees it (admin/HR/manager roles), retention period, how to withdraw. Explicit accept action, re-authenticated with biometrics/password. Withdrawal is one tap in Profile and immediately stops regions and revokes the device credential.

Texts live in `frontend/src/locales/worktime.ts` (`mn` source of truth, `ru` mirror, `en` optional) with a `policy_version` constant; any text change bumps the version and re-prompts. **Legal review of the mn/ru text is required before publishing** (same rule as the legal texts in `locales/legal.ts`).

Compliance notes (recommendations, not legal advice):
- Consent given by an employee is often not considered freely given; the company should also have the practice in its labour policy/contract, and must provide an alternative (QR / manual start) so refusing consent is not penalised. The app keeps those paths.
- Check requirements under Mongolia's personal-data protection law and any sector rules; confirm retention and cross-border storage with counsel.
- Apple: Precise Location in the privacy label ("linked to user", "App Functionality"), reviewer notes + demo account + explanation of the "Always" permission. Google Play: Background Location declaration with a video of the disclosure and a Data Safety entry.
- Worker transparency page in Profile: permission status, last event, list of the events the company stored, and a data-deletion/export request.

## 4. Biometric login

- Plugin: `@aparajita/capacitor-biometric-auth` (same maintainer as the secure-storage plugin already in use; Face ID, Touch ID, Android `BiometricPrompt`).
- Behaviour: opt-in (offered at first login on a native device) app lock. Cold start and resume after N minutes (default 5) require biometrics (device passcode as fallback) before `getNativeRefreshToken()` is read and the app unlocks. Password and Telegram sign-in remain as fallback; N failures → full login.
- Also used as step-up for: accepting consent, enabling/disabling automatic tracking, and optionally payroll/contract views.
- Limitation to state clearly: this is an app-level gate in JS over the existing Keychain/Keystore token, not a hardware-bound key. A stronger variant (token stored behind a biometric ACL) is possible later with a different storage plugin; it needs a binary update.
- Optional later: passkeys (WebAuthn) for server-verified biometric login; the Associated Domains / assetlinks files are already generated by the frontend entrypoint.
- Web build must not call any of this (`isNativePlatform()` guard), as with push.

## 5. Native push for all notifications

- Generalize `chat_push` into a `mobile_push` job: `create_notifications` (`services/user_notifications.py`) enqueues one per recipient with dedup key; delivery re-checks category preferences (`services/notification_preferences.py`) and active devices.
- Android channels: add `oyuns-worktime` (and others by category) next to `oyuns-default` / `oyuns-chat-v1`. `target_url` stays single-slash internal only.
- Silent/data push to tell devices to re-fetch sites when an admin edits them.
- Informational worktime pushes for every automatic start/stop and for "needs review".
- Telegram keeps working in parallel; native push only goes to devices with an active registration.

## 6. Delivery pipeline ("update repo → apps update")

- GitHub Actions: on push to `master` → `npm test`, build → `ota:upload:staging`; manual approval → `ota:promote:production` with the exact uploaded bundle. Native binaries only on tags (macOS runner, signing secrets in CI secrets, never in the repo).
- Update `docs/mobile-release.md` (new permissions, plugin, min native version) and the status block in `CLAUDE.md` (the Capacitor/OTA shell is not mentioned there today).
- Remember: pushing to `master` already deploys web + API in Dokploy. New API endpoints must be backward compatible with the oldest binary in the field.

## 7. Phases (rough, one developer; store review time excluded)

| # | Phase | Output | Est. |
|---|---|---|---|
| 0 | Prereqs | Legal text drafted + reviewed, Apple/Google accounts, Firebase/APNs provisioned per `mobile-release.md`, OTA CI, decide retention/grace defaults | 1 wk (parallel) |
| 1 | Backend | Migration, models + RLS, consent/device/site/event APIs, rules engine, sweeper, generalized push, tests (unit + DB) | 2 wk |
| 2 | Native | `OyunsGeofence` iOS + Android, biometric plugin, manifest/plist keys, capability API | 2 wk |
| 3 | Frontend | Consent flow, enrollment, Profile card, admin sites/auto-mode UI (reuse `WorktimeMapPicker`), biometric lock, i18n | 1.5 wk |
| 4 | Pilot (shadow) | TestFlight + Play internal build, 5–10 staff, `shadow` mode, device matrix, tune | 2–3 wk |
| 5 | Release | Store submissions with location declarations, switch pilot to `on`, org-by-org rollout | 1–2 wk + review |

The **first binary should only ship after Phase 2 is complete** (all permissions in it) — everything after is OTA.

Test matrix for Phase 4: iPhone (current and previous iOS, Low Power Mode, Approximate vs Precise, force-quit, reboot before first unlock), Pixel (Doze), Samsung (battery optimization), at least one Xiaomi/Huawei/Oppo (autostart restrictions), airplane mode / offline queue, permission downgrade mid-day, mock-location app, two devices on one account.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Missed/late OS geofence events → wrong pay | Shadow mode, reconciliation snapshots, sweeper + `needs_review`, manager edit/approval |
| Store rejection for background location | Prominent disclosure, accurate declaration/video, QR fallback, demonstrate core-function use |
| Employee privacy/legal exposure | Two-sided disclaimer, enter/exit only (no route), retention job, role-limited access with audit, legal review, refusal does not block work |
| OEM battery killers on Android | Guidance screen, WorkManager retries, reconciliation, vendor plugin fallback |
| Spoofed location | Mock flag, accuracy, impossible-travel, per-device credential, QR audit; flag to HR |
| OTA bundle newer than binary | Capability API + `min_native_version` |
| Radius too small for OS to resolve | Enforce ≥ 100 m in auto mode |

## 9. Open items for the product owner

1. Exit behaviour: always **stop** (plan default), or treat exits inside a lunch window as a **break**?
2. Default grace (10 min), retention (90 days), accuracy threshold (100 m), schedule window per site (always vs. working hours).
3. Thin custom plugin vs. commercial plugin (section 3.4).
4. Who may see location events (plan: admin and HR; managers only see resulting time entries).
5. Should refusing automatic tracking be allowed per employee (plan: yes, falls back to QR/manual) or mandatory by role?
