# OYUNS Workspace mobile release runbook

The React/Vite app in `frontend/` remains the single source of truth for web, iOS, and Android. Capacitor packages `frontend/dist` into native projects. The self-hosted OYUNS updater serves only those packaged web assets. Native plugins, entitlements, signing, privacy declarations, and store metadata always require a new store binary.

## Prerequisites and required provisioning

- Node.js 22 or newer.
- `zip` available in the release shell/CI runner (the OTA upload script packages `dist` as a ZIP).
- Capacitor 8-compatible Xcode, an Apple Developer team, bundle ID `mn.oyuns.workspace`, an APNs-enabled App ID, and signing profiles. Final APNs validation requires a signed physical device.
- Android Studio with Android SDK 36 and JDK 21, a Firebase Android app whose package is exactly `mn.oyuns.workspace`, and its client-only `google-services.json` at `frontend/android/app/google-services.json`. Gradle 8.14.3 does not support Java 26; the Android npm scripts use `frontend/scripts/with-java21.sh` to select JDK 21 automatically when it is installed through macOS `/usr/libexec/java_home` or Homebrew.
- An OYUNS backend deployment with `OTA_ENABLED=true`, a persistent `/app/uploads/ota` volume, and a long random `OTA_UPLOAD_TOKEN` stored only in CI/Dokploy secrets.
- Backend deployment with `NATIVE_APP_ORIGINS=capacitor://localhost,https://localhost` and production TLS at `https://erp.oyuns.mn`.

Never commit `google-services.json`, keystores, provisioning profiles, APNs credentials, Firebase service accounts, or `OTA_UPLOAD_TOKEN`. The Firebase client file is ignored because it is environment-specific; provision it from CI secrets or an approved developer credential store.

## First-time self-hosted updater setup

1. Generate a long random upload token and set it as `OTA_UPLOAD_TOKEN` in the backend deployment. Do not put it in the frontend build or a repository file.
2. Set `OTA_ENABLED=true`, `OTA_PUBLIC_BASE_URL=https://erp.oyuns.mn/api/v1/mobile-updates`, and mount a persistent volume at `/app/uploads/ota`.
3. Run the latest Alembic migration. The backend creates immutable bundle metadata and active/previous channel pointers.
4. Use `staging` for internal builds and `production` for store builds. The channel is compiled into the Vite bundle with `VITE_OTA_CHANNEL`; it is not changed by end users.

The native `@capgo/capacitor-updater` package is used only as the on-device ZIP installer and readiness/rollback engine. `autoUpdate` is off and `statsUrl` is empty, so the app does not contact Capgo Cloud. The OYUNS API performs channel checks and returns an HTTPS bundle URL plus SHA-256 checksum.

The native icon/splash master is `frontend/resources/icon.png`; generated iOS and Android assets are committed so normal `cap sync` does not require an image-processing dependency.

## Development and native builds

Browser development remains unchanged:

```bash
cd frontend
npm run dev
```

For a device or emulator on the same network, determine the host LAN address and run:

```bash
CAP_LIVE_HOST=192.0.2.10 npm run dev:mobile
CAP_LIVE_HOST=192.0.2.10 npm run native:live:ios
# or
CAP_LIVE_HOST=192.0.2.10 npm run native:live:android
```

Capacitor 8 uses `-l --host <LAN_IP> --port 5173`; it does not support Ionic CLI's `--external` flag. Live reload uses the Vite `/api` and WebSocket proxy. No development `server.url` is committed.

For a bundled production build:

```bash
VITE_NATIVE_API_ORIGIN=https://erp.oyuns.mn \
VITE_OTA_CHANNEL=production \
npm run native:sync
```

Use `VITE_OTA_CHANNEL=staging` for internal/TestFlight/Play Internal binaries. Then run `npm run native:open:ios` or `npm run native:open:android` to choose the signing team, archive, and publish. `native:prepare:ios` and `native:prepare:android` run tests and synchronization before opening the native IDE.

## Push notification provisioning and checks

Provider delivery is disabled until `MOBILE_PUSH_DELIVERY_ENABLED=true`. The worker reads credentials only from deployment secrets:

```env
MOBILE_PUSH_DELIVERY_ENABLED=true
FCM_PROJECT_ID=oyuns-finance
FCM_SERVICE_ACCOUNT_JSON={...single-line service account JSON...}
APNS_TEAM_ID=...
APNS_KEY_ID=...
APNS_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----
APNS_BUNDLE_ID=mn.oyuns.workspace
APNS_USE_SANDBOX=false
```

Never expose these values to the Vite bundle. The backend queues one idempotent `chat_push` worker job per eligible recipient, re-checks conversation membership and mute state at delivery time, and deactivates provider-rejected device tokens.

Every bell notification (tasks, reports, work time, calendar, contracts, HR, CRM, payroll) also gets a native copy: `create_notifications` queues a `notification_push` job per created notification. It follows the tenant rules and the recipient's own notification preferences (the bell entry is only created when they allow it), honours the same quiet hours as the Telegram copy, is skipped when the notification was read meanwhile, and is delivered on the `oyuns-default` channel with the notification's internal `target_url`.

### iOS/APNs

1. In Apple Developer/Xcode, confirm `mn.oyuns.workspace`, the Push Notifications capability, the correct team, and `aps-environment` entitlement.
2. Confirm `AppDelegate.swift` forwards registration success and failure to Capacitor.
3. Install on a signed physical device. Grant permission from Profile, verify an APNs token enrollment, then inspect the backend row: the recoverable token must be encrypted and only the SHA-256 hash may be used for uniqueness.
4. Send a controlled provider test payload. Foreground receipt must invalidate the existing in-app notification query; an action may navigate only to a single-slash internal `target_url`.

The simulator is suitable for UI and simulated payload checks, but physical-device registration/delivery is the release gate.

### Android/FCM

1. Provision `frontend/android/app/google-services.json` without committing it.
2. Sync and build with SDK 36; confirm the generated package is `mn.oyuns.workspace` and produce a signed AAB.
3. On Android 13+, verify the native permission prompt appears only after the Profile action. Android 12 and older should register without an OS prompt.
4. Confirm channels `oyuns-default` and `oyuns-chat-v1`, the custom chat sound, monochrome status icon, enrollment as provider `fcm`, token rotation, foreground/background payloads, Doze behavior, and both Play-enabled emulator and physical-device delivery.

Permission rejection never disables the in-app bell. The app does not repeatedly prompt after denial; the Profile control directs the user to device settings. Logout attempts backend revocation before deleting native session credentials. An offline revocation is retained securely and retried before the next registration.

## Native Telegram sign-in

Native sign-in uses Telegram's OIDC Authorization Code flow with PKCE. The app opens the system browser, then Telegram returns to the HTTPS callback below. The callback is intercepted by the installed app through Universal Links/App Links; the backend exchanges the code and issues the normal native refresh session.

1. In BotFather, open Bot Settings → Web Login and register:
   `https://erp.oyuns.mn/mobile-auth/telegram/callback`.
2. Store the resulting Client ID and Client Secret only in backend secrets:

```env
TELEGRAM_OIDC_CLIENT_ID=...
TELEGRAM_OIDC_CLIENT_SECRET=...
TELEGRAM_OIDC_REDIRECT_URI=https://erp.oyuns.mn/api/v1/auth/telegram/callback
TELEGRAM_OIDC_NATIVE_REDIRECT_URI=https://erp.oyuns.mn/mobile-auth/telegram/callback
TELEGRAM_OIDC_ISSUER=https://oauth.telegram.org
```

3. Set `APPLE_TEAM_ID` in the frontend container. Its entrypoint generates `/.well-known/apple-app-site-association` with the OYUNS bundle ID.
4. Set `ANDROID_SIGNING_CERT_SHA256` to a comma-separated list of the debug, internal, and production signing fingerprints. The frontend entrypoint generates `/.well-known/assetlinks.json` for `mn.oyuns.workspace`.
5. Deploy the backend and association files before installing the native binary. Verify both URLs return HTTPS `200`, JSON content, no redirect, and the exact callback path.

The native login screen shows Telegram first when the backend capability is configured and retains username/password as a fallback. The browser uses the separate `/api/v1/auth/telegram/callback` OIDC callback, while `/tg` Mini App authentication remains unchanged. A change to the App Link intent filter, Associated Domains entitlement, or signing fingerprints requires a new store binary; it cannot be delivered through OTA.

For local Android verification, include the debug keystore fingerprint from `keytool -list -v -keystore ~/.android/debug.keystore -alias androiddebugkey -storepass android`. Release and Play signing fingerprints must also be present in `ANDROID_SIGNING_CERT_SHA256`. The backend never places the OIDC client secret, provider tokens, PKCE verifier, or ID token in the native bundle.

## Self-hosted OTA upload, promotion, and rollback

Every bundle version must be unique and semantic. Upload only assets produced by the tested source tree:

```bash
export OTA_BUNDLE_VERSION=1.0.1
export OTA_UPLOAD_TOKEN='set-in-your-secret-manager'
export OTA_API_URL=https://erp.oyuns.mn/api/v1/mobile-updates
npm run ota:upload:staging
```

Validate that only staging devices receive it. The updater checks on foreground and hourly, downloads in the background, and activates after backgrounding/restart. It does not block splash or offline boot. After device acceptance, promote the exact uploaded bundle rather than rebuilding it:

```bash
OTA_BUNDLE_VERSION=1.0.1 npm run ota:promote:production
OTA_CHANNEL=production npm run ota:doctor
```

The React boot boundary installs sanitized Sentry breadcrumbs and calls `notifyAppReady()` after the tree commits but before passive session/network effects. A bundle that cannot import or commit withholds readiness and must roll back after the configured 10-second timeout/relaunch. To test, upload a deliberately boot-failing version to staging only, then confirm fallback to the prior/built-in bundle.

Failures after `notifyAppReady()` are not automatic rollback candidates. Reassign the previous known-good bundle to production:

```bash
OTA_BUNDLE_VERSION=1.0.0 npm run ota:promote:production
```

Verify corrupt/checksum-failed downloads, updater API outage, slow network, and offline launch retain the last working bundle. A newer native store build resets downloaded bundles according to `resetWhenUpdate`.

The upload script runs tests, creates a ZIP from `dist`, and calls `POST /api/v1/mobile-updates/bundles`. Promotion calls `PUT /channels/{channel}/bundle/{version}`; rollback calls `POST /channels/{channel}/rollback`. The backend stores bundles on the persistent volume and serves immutable, checksum-validated downloads. If end-to-end encrypted bundles are needed later, add that signing/encryption layer to this API and ship its public key in a new native binary.

## CI for OTA

- `.github/workflows/ota-staging.yml` runs on every push to `master` that touches `frontend/**`: tests, build, upload as `1.0.<run>.<attempt>`, activate on the `staging` channel. (It used to watch `main`, which does not exist here, so it never ran.)
- `.github/workflows/ota-production.yml` is manual (`workflow_dispatch`): it promotes an already tested staging version to `production` without rebuilding.
- Both need the `OTA_UPLOAD_TOKEN` secret in the `staging` / `production` GitHub environments; `OTA_API_URL` is an optional variable.

## Native capabilities and `min_native_version`

The web layer ships over the air and can run on an older binary, so two things keep it safe:

1. **Feature detection.** Every binary from native build 2 on has the `NativeCapabilities` plugin: `getNativeCapabilities()` → `{ nativeVersion, geofence, biometric }` (`src/platform/native-capabilities.ts`). A binary without the plugin is build 1 with no capabilities. Web code must ask before using a native plugin (`geofenceSupported()`, `biometricAvailability()`) and hide the feature otherwise.
2. **Server-side hold-back.** `frontend/native-requirements.json` holds `min_native_version`, the lowest binary build the bundle can run on at all. The upload script sends it, the server stores it on the bundle, and `/v1/mobile-updates/check` (which now receives `native_version`) does not offer the bundle to an older binary. Leave it at `1` while the bundle feature-detects; raise it only for a bundle that cannot boot on an older binary.

When a store binary adds a native capability, bump `oyunsNativeVersion` (`ios/App/App/GeofenceEngine.swift`) and `GeofenceStore.NATIVE_VERSION` (Android) together, and the capability number the plugin reports.

Rule for the first binary: every permission, `Info.plist` key, receiver and entitlement a later feature may need goes in now, because none of them can be delivered over the air.

## Automatic work time, biometrics and native capabilities

Product rules and the list of what is and is not verified: [`MOBILE APP PLAN.MD`](../MOBILE%20APP%20PLAN.MD).

### How it fits together

```
Admin: Settings → Ажлын цаг ба процесс → «Автомат цаг бүртгэл» — mode off / shadow / on (employer acknowledgement), office areas
Employee: Profile → «Автомат цаг бүртгэл» → disclaimer → consent → "always" location → device enrolled
Phone (native, also with the app closed): registers the areas, reports enter / exit / snapshots with its device credential
Server: rules → WorkTimeEntry (source_channel = geofence) → audit → bell + push notification
Worker: finalises exits after the grace, closes clocks left running overnight, purges old events
```

- **Device credential.** Enrollment returns `"<device id>.<secret>"` once; only its SHA-256 is stored. The web layer hands it to the native plugin, which keeps it in the Keychain (iOS, `AfterFirstUnlockThisDeviceOnly`) or encrypts it with an Android Keystore key. It is sent as `Authorization: Device …` and opens only `GET /v1/mobile/geofences` and `POST /v1/mobile/geo-events`. The session refresh token is never given to native code.
- **Decisions are server-side** (`backend/app/services/worktime_auto.py`). The phone only registers regions and reports. Sites and the mode come back with every report, so an admin change reaches phones on their next event or 15-minute snapshot.
- **Shadow mode** records what would have happened (`shadow:start`, `shadow:stop`) and changes nothing. Roll every tenant out in shadow mode first and compare the log with real attendance.
- **Worker required.** `python -m app.worker` finalises pending exits every 30 seconds, sweeps stale clocks every 15 minutes and purges events daily. Without it exits are only finalised when the same phone reports again.

### Reliability on Android

- Geofences are registered through Google Play services with no initial trigger. They do not survive a reboot, an app update or a Play services reset, so `GeofenceBootReceiver` and a 15-minute periodic `WorkManager` job re-register them and send an inside/outside snapshot, which repairs a transition the system never delivered.
- The employee card asks for the battery-optimisation exemption right after enrollment (`ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`) and links to the manufacturer's auto-start screen (Xiaomi, Huawei/Honor, Oppo/Realme, Vivo, Samsung, OnePlus, Asus, Transsion). The server stores what the phone reports (`location_permission`, `location_accuracy`, `battery_unrestricted`); admin and HR see unhealthy phones in the device list.
- Areas smaller than 100 m are registered as 100 m on both platforms.

### Release checklist for the binary that introduces this

1. iOS: build in Xcode (the Swift sources were not compiled on the machine that wrote them). Confirm the Info.plist purpose strings, `UIBackgroundModes` (`location`, `remote-notification`) and that `GeofenceEngine.shared.start()` runs in `didFinishLaunching`.
2. Android: `npm run native:sync:android`, build the AAB. New dependencies: `play-services-location`, `work-runtime`, `biometric`.
3. Bump `versionCode` / `versionName` and `CURRENT_PROJECT_VERSION` / `MARKETING_VERSION`.
4. Store declarations: Play "background location" declaration with a short video of the consent dialog and the feature; Play justification for the battery-optimisation exemption; App Store review notes explaining region monitoring, the opt-in consent and the QR/manual alternative.
5. Device tests, each on a physical phone, with the tenant in `shadow` and then `on`: enter and exit with the app in foreground, in background and force-closed; phone rebooted while outside, then entering; airplane mode during an exit, then back online (late report stops the clock at the exit time); step out and back within the grace; permission downgraded to "while using"; consent withdrawn (phone stops within one report); a second phone enrolled (the first one stops); mock-location app on Android (flagged, no clock change). Repeat on at least one Xiaomi/Huawei/Oppo and one Samsung with battery saver on.
6. Biometric lock: enable in Profile, kill and reopen the app, background for over a minute, fail recognition and fall back to the screen lock, remove the phone's screen lock (the app must not trap the user).

## Web and security regression gates

- Run `npm test`, `npm run test:e2e`, and `npm run build`; deploy the same React source through the existing web pipeline.
- On web, verify no Capacitor push permission, browser Notification API, updater, or secure-storage method runs. Authentication remains HTTP-only refresh-cookie based and no refresh token appears in JSON.
- Verify the bell, unread count, priority/read actions, WebSocket invalidation, desktop selection/keyboard behavior, Telegram Mini App, popup OAuth, printing, downloads, microphone, and camera flows.
- Native refresh tokens live only in Keychain/Android Keystore and are returned/accepted only for exact allowlisted Capacitor origins. Push and refresh tokens must never be logged or sent to Sentry.
- APNs/FCM provider delivery remains a safe no-op until its feature flag and secrets are configured. Validate the custom sound on signed physical devices before production enablement.
