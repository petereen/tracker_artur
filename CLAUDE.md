# CLAUDE.md — OYUNS Agent

Инструкции для Claude Code по работе с этим проектом.

> 📄 **Продуктовое ТЗ (описательное, без тех. стека)** — как работает сервис и как взаимодействуют бот, Telegram Mini App и веб-кабинет: [`docs/portal-spec.md`](docs/portal-spec.md). Ключевой принцип: три канала поверх единого ядра, веб-кабинет сотрудника = основа Mini App.

## ✅ Статус проекта: АКТИВЕН на Dokploy (VPS) — `https://erp.oyuns.mn`

> **Прод = Dokploy на VPS** (`docker-compose.dokploy.yml`), API под `/api` (`/api/health`). **Деплой = push в `origin/master`** (github.com/petereen/tracker_artur): новые роуты появляются на проде через секунды после push. Проверка: незащищённый роут → `403` (есть) / `404` (нет), плюс смена хэша `assets/index-*.js`. CLI `az` локально не установлен.
> **Блок про Azure ACA ниже устарел** (исторический, актуальность не проверялась) — не использовать для деплоя. Раздел «Деплой изменений» с `docker compose` — тоже для локальной/старой схемы.
> **Рабочее дерево общее:** в нём параллельно правят другие люди/агенты. Коммить только свои hunk-и (`git apply --cached` с отфильтрованным патчем), проверять коммит в чистом `git worktree` (tsc + vitest + build + pytest) и только потом пушить в `master` (пуш = деплой, подтверждать у пользователя).

### i18n: монгольский / русский / английский (2026-10-01, в работе по этапам)
- **⚠️ Обязательное правило:** при любой реализации или изменении интерфейса (фронтенд-код, видимые пользователю строки, подписи, плейсхолдеры, тосты, ошибки, aria-label) **всегда** сразу добавлять переводы на **`ru` и `en`** (плюс `mn` как источник правды). Захардкоженных строк в JSX/TS быть не должно — только ключи `t('домен.ключ')`. Работа с UI не считается завершённой, пока у каждого нового ключа нет `mn`, `ru` и `en`.
- **Источник правды — `mn`.** Строки лежат в `frontend/src/locales/<домен>.ts` через `defineMessages({ mn, ru, en })` (`locales/define.ts`): ключи `ru` обязаны совпадать с `mn` (иначе `tsc` падает); `en` для новых и изменяемых строк **обязателен** (у старых строк без `en` фолбэк → `mn`; при правке таких строк — дополнять `en`). Новый домен — файл + строка в `locales/index.ts`. `locales/locales.test.ts` проверяет дубли ключей, parity ru/mn, одинаковые `{{плейсхолдеры}}` и что в `ru` нет монгольских букв Ө/Ү.
- **В коде:** `const { t } = useTranslation()` → `t('домен.ключ')`; вне компонентов (классы, `platform/`, toast из хуков) — `import i18n from '../i18n'` → `i18n.t(...)`. Без `defaultValue` и литералов-фолбэков. Интерполяция — `{{n}}`, не `count` (у ru свои plural-формы). Даты/числа — `intlLocale()` из `utils/locale.ts` (не `'mn-MN'` вручную).
- **Язык:** `i18n.ts` читает `localStorage['oyuns.language']` (по умолчанию `mn`), ставит `<html lang>`; после входа `EnterpriseShell` подтягивает `actor.locale`; на экранах без входа — `LanguageSwitcher`. `test/setup.ts` импортирует `i18n` (тесты идут на `mn`, тексты `mn` менять нельзя без правки тестов).
- **Загрузка языков (2026-10-05):** приложение грузит только активный язык. `vite-plugins/localeSplit.ts` собирает из доменных файлов виртуальные модули `virtual:oyuns-locale/<mn|ru|en>` (значения в `defineMessages` — только строковые литералы, иначе сборка падает), `i18n.ts` подтягивает язык через i18next-backend, `main.tsx` рендерит после `i18nReady`; смена языка (`changeLanguage`) сначала догружает каталог. `fallbackLng` выключен (иначе подтянется и `mn`) — полнота ключей гарантируют `tsc` и `locales.test.ts`. **Код приложения не должен импортировать `locales/index.ts` (`messageSets`/`resources`) — это вернёт все три языка в бандл; список языков — из `locales/languages.ts`.** Новый домен по-прежнему регистрируется в `locales/index.ts` (плагин читает оттуда список). Тесты ждут `i18nReady` в `test/setup.ts`.
- **Бюджет производительности:** `npm run performance:budget` (`scripts/check-performance-budget.mjs`; для проверки без повторной сборки — `PERF_DIST=<dir>`). Считает граф первой загрузки по manifest + самый большой каталог языка. Тяжёлые страничные библиотеки (markdown, socket.io, qrcode, dnd-kit, motion) вынесены в отдельные чанки в `vite.config.ts` — не возвращать их в общий `vendor` (он грузится на первом экране); `CallModal` и `Grainient` — lazy.
- **Тексты вне React и реестры (М2):** заголовки/описания виджетов — по ключам `today.widget.<type>.title|description|keywords` (`widgetTitleKey()` в `today/types.ts`, в `registry.tsx` их больше нет); модульные константы с подписями (`COLUMNS`, `CALENDAR_FILTERS`, `taskCollaborationLabels`) — геттеры с `i18n.t`, чтобы подпись читалась на языке интерфейса в момент рендера; фразы звонка (Chimege/ElevenLabs) — `i18n.t(key, { lng: язык звонка })`; текст, вставляемый в пост (`markdownEditing.ts`), берётся при нажатии кнопки.
- **Прогресс:** `npm run i18n:audit` (в `frontend/`) — файлы с захардкоженной кириллицей (видит только кириллицу, не английские литералы; мёртвые файлы в списке `DEAD` скрипта). Сделано: этап 1 — оболочка (навигация, шапка, мобильное меню, команд-бар, drawer работников), логин/сброс пароля, `TenantGate`, `SeatLimitNotice`, уведомления, `Loading`, `WorkdayStartButton`. Этап 2 (2026-10-01) — Today (холст, реестр и все виджеты, библиотека, настройки), новости/`AnnouncementsPage`, чат (`ChatWorkspacePage`, звонки, `useWebRTC`), OYUNS AI (`OyunsAssistant`, `OyunsVoiceCall`, `chimegeCall`/`elevenlabsCall`), задачи, календарь (+ мобильный), мировые часы, KPI-drilldown, `TimePeriodFilter`; домены `today`, `chat`, `assistant`, `tasks`, `calendar`. Этап 3 (2026-10-01) — время (`WorktimePage`, QR-экран, сетка ирц `attendance/**`, экспорт, статистика, карта), HR (`HRWorkspacePage`, `EmployeesPage`, меню работника), отчёты (список/согласование, политика, AI-сводка), планы, проекты, загрузка команды, профиль (+ `i18n.changeLanguage` после сохранения языка), расписание, анкета, онбординг, база знаний, разработка, вопросы check-in, Mini App; домены `worktime`, `hr`, `reports`, `plans`, `projects`, `profile`. Токены `{нэр}`/`{цаг}` шаблона приветствия — протокол бота, одинаковы во всех языках; названия ролей Member/Manager/… и «Telegram ID/username» оставлены как есть. Этап 4 (2026-10-01) — договоры (`ContractsWorkspacePage` вместе со страницей печати — печатается на языке интерфейса, `ContractRegistryFields`, архив, `RichContractEditor`), CRM (`crm/**`), бюджет (`budget/**`), план счетов (`ChartOfAccountsPage`, `accounts/**`); домены `contracts`, `crm`, `budget`, `accounts`. Модульные таблицы подписей (статусы/виды/сценарии бюджета, классы счетов, `CATEGORY_LABELS`, типы ссылок) — `labelMap()`/`labelOr()` из `utils/labelMap.ts` (геттеры, читают язык при каждом обращении; экспортируемые имена сохранены, их используют и файлы М5). Числа/даты — `intlLocale()`. Значения-данные бэкенда (категория архива «Бусад», названия классов/назначений счетов из каталога API, `detail`-строки FastAPI) не переводятся; строки с `i18n-ignore` аудит пропускает. ТТД→«ИНН», РД→«Рег. №», НХАТ оставлен аббревиатурой — термины для проверки.
- **М5–М7 (2026-10-02, `npm run i18n:audit` = 0 файлов):** М5 расчёт зарплаты (`pages/monthly-payroll/**`, `MonthlyPayrollWorkspace`, `MonthlyPayrollProfileDrawer`; домен `payrollRun`, ключи `mp.*`; русские термины: НДШ→«соцвзносы», ХХОАТ→«НДФЛ», сүүл цалин→«остаток зарплаты», урьдчилгаа→«аванс», БНДШ→«соцвзносы работодателя» — для проверки бухгалтером); М6 настройки/консоль/юр. тексты (домены `settings` `st.*`, `console` `con.*`/`ct.*`/`cc.*`, `legal` — юр. тексты переведены дословно, **показать юристу перед публикацией**); М7 тосты API-хуков (`api/hooks.ts`, `api/enterprise.ts`, домен `api` `api.*`), `intlLocale()` вместо `'mn-MN'`/`localeCompare(…,'mn')`. Подписи каталогов, приходящие с бэкенда на монгольском (категории уведомлений, разделы прав AI, каталог ролей, модули лицензии), переводятся оверлеем `catalogText(key, serverText)` (`utils/labelMap.ts`, домен `catalogs` `cat.*`: mn = текст бэкенда, для `mn` используется ответ сервера; неизвестный код → текст сервера). Не переведено сознательно: данные бэкенда (типы удержаний по умолчанию, категория архива «Бусад», `detail` FastAPI), сообщения Telegram-бота и уведомления бэкенда (монгольские), PWA `manifest.webmanifest` (статичный файл), английские подписи в `ERPBuilderPanels`. `PayrollWorkspaceUI.tsx` добавлен в `DEAD` аудита. Модульные экспортируемые таблицы с подписями (`LICENSE_STATE`, `TENANT_STATUS`, `CYCLES`) — объекты с геттерами `get label()`.

### Мобильное приложение: автоучёт времени по геозонам, биометрия, push, OTA-гейтинг (2026-10-02)
- **План и статус:** [`MOBILE APP PLAN.MD`](MOBILE%20APP%20PLAN.MD) (раздел «Implementation status» — что сделано и что НЕ проверено), ранбук — [`docs/mobile-release.md`](docs/mobile-release.md). ⚠️ iOS-код (`GeofenceEngine.swift`, `GeofencePlugin.swift`, `BiometricAuthPlugin.swift`, `NativeCapabilitiesPlugin.swift`) **не компилировался** (лицензия Xcode не принята), на реальных телефонах ничего не тестировалось; Android debug APK собирается.
- **Правило «нативный слой только сообщает»:** телефон регистрирует геозоны и шлёт `enter|exit|state_inside|state_outside`; все решения — на сервере, `app/services/worktime_auto.py` (`decide` — чистая функция). Выход всегда останавливает часы (и во время перерыва), остановка — моментом выхода после `exit_grace_minutes` (вернулся раньше → `ignored:returned`); снимок `state_inside` только чинит пропущенный вход и не перезапускает часы, остановленные вручную; remote-сессии не трогаются; mock-локация / точность хуже порога / опоздание > 6 ч / несовпадение позиции → без изменений + `needs_review`. Координаты **не хранятся**.
- **Модель** (`app/models/worktime_geo.py`, миграция `7d9b3f5a1e48` после `6c8a2e4f0d37`, RLS): `worktime_sites` (первая активная зона = legacy `settings["worktime_geofence"]`, синхронизация в обе стороны; ручной старт принимает любую активную зону), `worktime_location_consents` (append-only), `mobile_devices` (хранится только SHA-256 креденшела; **один телефон на аккаунт**), `worktime_geo_events` (идемпотентность `(device_id, client_event_id)`), `mobile_update_bundles.min_native_version`.
- **Настройки** лежат в том же ключе `organization.settings["worktime_methods"]`: `auto_geofence_mode off|shadow|on`, `exit_grace_minutes` (10), `min_accuracy_meters` (100), `geo_retention_days` (90), `employer_disclaimer_ack`. `GET/PUT /v1/settings/worktime-auto` (PUT — admin; режим ≠ off требует подтверждения работодателя текущей `POLICY_VERSION`, иначе 409 `employer_disclaimer_required`). ⚠️ `PUT /settings/worktime-methods` теперь мержит ключ, а не перезаписывает — не ломать.
- **API** (`app/routers/worktime_geo.py`, префикс `/v1`): сотрудник — `/worktime/auto/status|consent-text|consent`, `POST /mobile/devices` (нужны согласие и режим ≠ off; креденшел `"<id>.<secret>"` отдаётся один раз), `PUT /mobile/devices/{id}/state`; нативный слой — `GET /mobile/geofences`, `POST /mobile/geo-events` с `Authorization: Device …` (зависимость `get_device`: поиск в `system_scope`, затем `bind_tenant`; 401 `device_revoked` → телефон сам отключается); админ — `/worktime/sites` (CRUD, ≤20 активных), `/worktime/auto/devices`, `/worktime/auto/events` (**только admin и hr**, чтение пишется в аудит `operation="viewed"`).
- **Тексты согласия** (mn/ru/en) и `POLICY_VERSION` — в `worktime_auto.py`; смена текста = новая версия = повторное согласие всех. Тексты — черновики, **показать юристу**.
- **Worker** (`app/worker.py`): `finalize_pending_exits` (30 с), `close_stale_entries` (15 мин; закрывает geofence-часы, оставшиеся с прошлого дня, по последнему подтверждённому присутствию, `needs_review`), `purge_geo_events` (раз в сутки). Без запущенного worker выходы финализируются только при следующем событии того же телефона.
- **Push для всех уведомлений:** `create_notifications` и `mirror_existing_telegram_notification` ставят джоб `notification_push` (`deliver_notification_push` в `mobile_push_delivery.py`, канал `oyuns-default`, тихие часы как у Telegram-копии). Новые kind'ы `worktime_auto_started|stopped` (категория `worktime`, без Telegram-копии).
- **Нативные плагины:** `Geofence`, `BiometricAuth`, `NativeCapabilities` (iOS — `ios/App/App/*.swift`, регистрация в `SceneDelegate`, `GeofenceEngine.shared.start()` в `AppDelegate`; Android — `mn.oyuns.workspace.geofence.*` + `BiometricAuthPlugin`, регистрация в `MainActivity`). Android: `GeofenceBootReceiver` + периодический `WorkManager` (15 мин) перерегистрируют зоны и шлют снимок; запрос исключения из оптимизации батареи и экран автозапуска производителя. Версия нативного слоя — `oyunsNativeVersion` (Swift) и `GeofenceStore.NATIVE_VERSION` (Java), сейчас `2`, менять вместе.
- **Веб-слой:** `platform/native-capabilities.ts` (бинарник без плагина = сборка 1, фичи скрываются), `platform/geofence.ts`, `platform/biometric.ts`, `platform/auto-worktime.ts` (синхронизация при старте/resume, отключение при выходе из аккаунта), `api/worktimeAuto.ts`. UI: `AutoWorktimeCard` и `BiometricLockCard` в профиле, `BiometricLockGate` в `App.tsx` (блокировка при холодном старте и после 1 мин в фоне, фолбэк на блокировку экрана), `WorktimeAutoSettings` (Настройки → Ажлын цаг ба процесс), `WorktimeLocationLog` (там же и HR → ирц для hr). Домен переводов `worktimeAuto` (`wta.*`).
- **OTA:** `ota-staging.yml` слушает `master` (+ фильтр `frontend/**`); `frontend/native-requirements.json` → `min_native_version` бандла; `/v1/mobile-updates/check` принимает `native_version`.
- **Тесты:** `test_worktime_auto.py`, DB — `test_worktime_auto_db.py` (`GEO_TEST_DATABASE_URL`), `test_alembic_graph.py` (голова `7d9b3f5a1e48`); фронт — `native-capabilities.test.ts`, `self-hosted-updater.test.ts`, `AutoWorktimeCard.test.tsx`, `BiometricLock.test.tsx`, `WorktimeAutoSettings.test.tsx`.
- **Не сделано:** Telegram-старт проверяет только первую зону; расписание смен сотрудника не учитывается (только окно времени зоны); принудительный logout (истёкшая сессия) не отключает телефон — только явный выход.

### OYUNS ERP — мультитенантный SaaS (2026-09-29, ветка `claude/trusting-mayer-rbex7g`)
- **Полное описание:** [`docs/multi-tenancy.md`](docs/multi-tenancy.md) (blueprint, DDL, токены лицензий, пошаговый перевод прод-VPS). Миграция `b3c4d5e6f7a8` (после `a8b9c0d1e2f3`).
- **Тенант = `organizations`** (slug, status `pending_activation|active|suspended|terminated`, `is_primary`, plan/billing, `seat_limit` NULL = ∞, `features`, `license_required`, `license_expires_at`, `branding`). Существующая компания = **основной тенант** (все модули, без лимита, `license_required=false`) — для текущих пользователей ничего не меняется.
- **Изоляция — 3 слоя:** фильтры `organization_id` в коде + ORM-guard (`app/core/tenancy.py`: чужая строка при загрузке/записи → `TenantBoundaryViolation` → 403 `tenant_boundary`; новые строки штампуются тенантом) + PostgreSQL RLS на всех 148 таблицах с `organization_id` (`tenant_row_visible`, `app.tenant_id` ставится на каждую транзакцию в `after_begin`). ⚠️ RLS не действует для superuser (`tracker` в docker) — для реальной защиты API должен ходить под `oyuns_app` (`ops/sql/oyuns_app_role.sql`, `MIGRATION_DATABASE_URL` = владелец для Alembic). Без тенанта (бот, планировщик, консоль, миграции) — системный контекст.
- **Middleware** `app/core/tenant_middleware.py`: тенант из хоста (`<slug>.TENANT_BASE_DOMAIN` / `tenant_domains`) и из JWT; несовпадение → 403 `tenant_mismatch`; suspended → 403; нет/истекла лицензия → 402 (кроме `/v1/auth/*`, `/v1/tenant/*`); модуль вне лицензии → 403 `feature_not_licensed` (`FEATURE_ROUTES`). Legacy-экраны без tenant-ключа (`/questions`, `/dashboard`, `/tasks`, `/auth/*`…) — фича `legacy_workspace`, только для основного тенанта. Новые эндпоинты модулей — добавлять префикс в `FEATURE_ROUTES`.
- **Лицензии:** Ed25519 JWS (`app/services/licensing.py`, `kid`-ротация через `LICENSE_PUBLIC_KEYS`) + реестр `tenant_licenses` (отзыв/замена, один `active` на тенанта). Активация — `POST /v1/tenant/license/activate` (админ по *выданной* роли), UI: Настройки → Систем ба аюулгүй байдал → «Лиценз ба идэвхжүүлэлт»; без лицензии фронт показывает экран активации (`components/TenantGate.tsx`).
- **Места (seats):** аккаунты `active|invited|locked`, не системные агенты. `ensure_seat_available` (блокирует строку тенанта) на всех путях создания/реактивации логина + триггер `enforce_tenant_seat_limit` (SQLSTATE `OY001` → 409 `seat_limit_reached`). Глобальная уникальность логина/Telegram под RLS — `identity_in_use` (SQL `platform_identity_in_use`).
- **Консоль оператора** `/platform` (`frontend/src/console/*`, API `/v1/platform`, `app/routers/platform.py`): отдельная таблица `platform_operators` (superadmin / support только чтение), свой токен (другой ключ и audience), аудит `platform_audit_logs`. Первый оператор — `PLATFORM_BOOTSTRAP_EMAIL/PASSWORD`; CLI `python -m scripts.platform_admin generate-license-keys|create-operator|tenants|rls-status`.
- **Брендинг:** `organizations.branding` (имя, logo/favicon URL, цвета) → `GET /v1/tenant/branding` (публичный, по хосту); фронт перекрашивает Astryx-тему и legacy `--color-accent` (`theme/tenantBranding.ts`).
- **⚠️ Gotcha:** старая миграция `q5r6s7t8u9v0` раньше строила `organizations` из живой модели — теперь из замороженного описания; миграции, создающие таблицы через `Base.metadata.tables[...]`, ломают чистую установку при изменении модели. Legacy-колонки `organization_id` (work_reports, questions, manager_settings…) не замаплены в ORM и защищены от autogenerate фильтром в `alembic/env.py`.
- **Тесты:** `tests/test_multi_tenant.py`; DB e2e — `tests/test_multi_tenant_db.py` (`TENANCY_TEST_DATABASE_URL`, пересоздаёт схему через `alembic upgrade head`, гоняет API под не-superuser ролью); фронт — `TenantLicenseSettings.test.tsx`, `theme/tenantBranding.test.ts`, `console/ConsoleApp.test.tsx`.

### 2FA для пользователей тенанта (2026-10-02)
- **Настройка:** Настройки → Систем ба аюулгүй байдал → Нэвтрэлт → «2 шатлалт нэвтрэлт» (`components/TwoFactorSettings.tsx`, только admin): `organization.settings["security"]["two_factor_required"]` (по умолчанию выкл.), `GET/PUT /v1/settings/two-factor` (ответ: `required`, `accounts`, `enrolled`). Значение кэшируется в `TenantState.two_factor_required` (`tenant_directory`, PUT инвалидирует кэш).
- **Принуждение — на сервере, на уровне сессии:** access-токен несёт `sid` (id `refresh_sessions`) и `mfa` (второй фактор пройден; `refresh_sessions.mfa_verified_at`, переносится при ротации). `actor_from_token` при включённом требовании и токене без `mfa` → 403 `two_factor_required` (все API и websocket). Без гейта работают только `get_session_actor`-эндпоинты: `GET /v1/auth/me` (отдаёт `two_factor: {required, enrolled, verified}`) и `/v1/auth/2fa/*`. Вход (пароль, Telegram, Mini App) по-прежнему выдаёт сессию — она «низкого уровня», пока не введён код. **Новый эндпоинт, который должен работать до 2FA, — через `get_session_actor`, иначе он закрыт.**
- **Поток:** `POST /v1/auth/2fa/setup` (секрет + `otpauth://`, issuer = имя тенанта) → `POST /2fa/enable` (первый код → сессия подтверждена, 10 recovery-кодов один раз) ; при следующих входах `POST /2fa/verify` (код приложения или recovery-код). Ответ enable/verify содержит новый access-токен. Неверные коды — в общий счётчик блокировки (5 / 15 мин, 423); пока код не введён, шаг пароля/Telegram счётчик не сбрасывает. Сброс (потерян телефон): админ → та же карточка настроек → «Шинэчлэх» (`POST /v1/auth/accounts/{id}/two-factor/reset`, снимает `mfa_verified_at` со всех сессий аккаунта). Выключение требования enrolment не удаляет.
- **UI:** `components/TwoFactorGate.tsx` — неотключаемый Astryx `Dialog purpose="required"` (настройка с QR или ввод кода, выход — только «Гарах»); `App.tsx` показывает его вместо приложения, когда `actor.two_factor` требует. Для уже вошедших: любой 403 `two_factor_required` → `api/client.ts` шлёт событие `TWO_FACTOR_REQUIRED_EVENT` → перечитывается `/me` → всплывает окно. Строки — домен `twoFactor` (`tfa.*`). TOTP — тот же `services/totp.py`, что у консоли оператора.
- **Миграция** `6c8a2e4f0d37` (после `5b7f1d3e9c26`): `user_accounts.totp_*`, `refresh_sessions.mfa_verified_at`. **Не покрыто:** Telegram-бот и `/miniapp/*` (initData), legacy `/auth/*` (`admin_users`), MCP-токены. **Единственный админ потерял доступ:** консоль оператора → карточка тенанта → «Админууд» (`AdminsCard` в `console/ConsoleTenants.tsx`, только superadmin): «2FA арилгах» / «Нууц үг дахин олгох» (`POST /v1/platform/tenants/{id}/admins/{account_id}/recover`, `password` и/или `reset_two_factor`; только аккаунты с ролью admin, временный пароль → `must_change_password`, сессии завершаются) и «Шинэ админ олгох» (`POST /v1/platform/tenants/{id}/admins`, занимает место). Всё пишется в `platform_audit_logs` (`tenant.admin_recovered`, `tenant.admin_issued`).
- **Тесты:** `test_tenant_two_factor.py`, `test_workspace_mode_scope.py`; фронт — `TwoFactorGate.test.tsx`.

### 2FA в консоли оператора (2026-10-01)
- **Вход в `/platform` двухшаговый:** `POST /v1/platform/auth/login` (пароль) больше **не** отдаёт `access_token` — только `two_factor: setup|verify` + `mfa_token` (10 мин, audience `oyuns-platform-mfa`, открывает только `/auth/2fa/*`). `setup` → `POST /auth/2fa/setup` (секрет + `otpauth://`) → `POST /auth/2fa/enable` (первый код → сессия + 10 recovery-кодов, показываются один раз); `verify` → `POST /auth/2fa/verify` (код приложения или recovery-код). `get_operator` отклоняет токены оператора без включённого 2FA.
- **TOTP** — `app/services/totp.py` (RFC 6238, SHA-1/6 цифр/30 с, ±1 шаг, без новых зависимостей): Google/Microsoft Authenticator, Authy, 1Password. Колонки `platform_operators.totp_*` (миграция `5b7f1d3e9c26` после `4a6e0c2d8b15`): секрет шифруется `secret_box`, `totp_last_step` — защита от повтора, recovery-коды хранятся SHA-256. Неверные коды идут в общий счётчик блокировки (5 попыток / 15 мин); при включённом 2FA шаг пароля счётчик не сбрасывает.
- **Сброс (потерян телефон):** Консол → Операторууд → «Шинэчлэх» (`PATCH /v1/platform/operators/{id}` `reset_two_factor: true`, завершает сессии этого оператора) или `python -m scripts.platform_admin reset-2fa --email …`.
- **UI:** `frontend/src/console/ConsoleTwoFactor.tsx` (шаги + QR через `qrcode.react`, ручной ключ, экран recovery-кодов), `ConsoleLogin` в `ConsoleApp.tsx`. Тесты: `test_operator_two_factor.py`, `test_multi_tenant_db.py`, `ConsoleApp.test.tsx`.

### Конструктор ролей, периоды отчётов, изоляция AI, уведомления, места (2026-09-30)
- **Конструктор ролей** (Настройки → Хэрэглэгч ба эрх → Үүрэг ба эрх, `components/RoleBuilder.tsx`; старый `RoleEditor` из `ERPBuilderPanels` удалён, там остался только конструктор форм). Роль = **платформенные роли** (`erp_access_roles.system_roles`, миграция `e1f2a3b4c5d6` после `d4e8f1a2b3c9`: member/team_lead/manager/hr/legal_counsel/client_auditor/contractor, **никогда admin**) + **права модулей** только из каталога реально проверяемых `require_capability` пар (`app/erp/role_catalog.py`, `GET /v1/erp/admin/roles/catalog`, нелицензированные модули скрыты). `custom_role_grants` в `enterprise_deps` добавляет роли из активных ролей (напрямую и через команду) в `actor.roles` (web и Telegram). Код роли необязателен (генерируется), дубли имени/назначения → 409, `DELETE` (без держателей) и `/activate`. Раньше API отклонял `crm_activity`/`budget`/`budget_settings`/`crm_settings` (422), а UI предлагал отключённые документы — отсюда «через раз». ⚠️ `list_accounts`/`_management_account_ids` по-прежнему видят только прямые `RoleAssignment`.
- **Периоды отчётов:** новый тип `half_yearly`; `report_policy["frequency_settings"][freq]` — `start_weekday` (неделя), `start_day` (месяц 26→25 и т.п.), `start_month` (финансовый год/квартал/полугодие), `reminder_days` (null = общий), `due_days` (дни после конца периода, когда отчёт ещё принимается и напоминается), `reminder_hour`. `open_report_periods` = окно «closing» + «overdue» (прошлый период в пределах `due_days`); `/v1/reports/options` отдаёт и просроченный период (`overdue`, `due_date`). Джоб `monthly_report_{emp}` теперь **ежечасный** (минута утреннего времени) и шлёт частоту в её `reminder_hour` (по умолчанию час утреннего времени); старые джобы без часа работают как раньше. Месячный личный отчёт в боте создаётся по периоду политики; дайджест за месяц берёт прошлый период политики.
- **Изоляция OYUNS AI по тенантам** (`services/ai_gateway/tenant_db.py`): `execute_turn` и `ToolRegistry.dispatch_tool` падают закрыто без тенанта или при чужом тенанте (`TenantIsolationError`), весь ход в `tenant_scope`; read-инструменты идут через `tenant_ai_session` — **отдельный пул соединений на тенанта** на движке `AI_DATABASE_URL` (роль `oyuns_ai` NOBYPASSRLS, `ops/sql/oyuns_ai_role.sql`; пусто → `DATABASE_URL`), каждая транзакция `app.tenant_id` + `app.rls_strict=on`. `AI_DATABASE_REQUIRE_RLS=true` — отказ, если роль обходит RLS (иначе предупреждение в логе). Circuit breaker и `exact_key` кэша — по тенанту. ⚠️ Для физической защиты на проде нужно создать `oyuns_ai` и задать `AI_DATABASE_URL`.
- **Уведомления** (`services/notification_preferences.py`): категории (tasks/reports/worktime/calendar/contracts/hr/crm/payroll/digests/checkin/system, `category_for(kind)`). Тенант: `organization.settings["notifications"]` (вкл., платформа, Telegram, «ажилтан өөрчилнө»), `GET/PUT /v1/settings/notifications` (admin), UI Настройки → Автоматжуулалт → «Мэдэгдлийн тохиргоо» (`components/NotificationSettings.tsx`). Пользователь: `user_accounts.preferences["notifications"]`, `GET/PUT /v1/auth/preferences/notifications`, карточка в профиле (`components/NotificationPreferencesCard.tsx`). Применяется в `create_notifications`, `task_service.enqueue_notification`, повторно при отправке outbox (`status='skipped'`), и в джобах бота (check-in, напоминания, worktime, отчёты, ДР, дайджесты). **Legacy check-in (`checkin`) по умолчанию выключен** и доступен только основному тенанту; утренняя/недельная сводка check-in и алерт «не заполнил» — тоже под ним. Telegram-сообщения: иконка категории + кнопка «Нээх», без старых `/done`/`/snooze` подсказок.
- **Места:** работник (HR-запись) добавляется и при полном лимите; админ/HR видят баннер `SeatLimitNotice`, `POST /v1/hr/employees` возвращает `seats`/`seat_warning`, `/v1/tenant/seats` доступен и HR. Меню «⋯» работника (`WorkerActionsMenu`) рендерится порталом с fixed-позицией (раньше обрезалось `overflow: hidden` карточки).
- **Тесты:** `test_role_catalog.py`, `test_report_policy.py`, `test_ai_tenant_isolation.py`, `test_notification_preferences.py`, `test_alembic_graph.py` (голова `e1f2a3b4c5d6`); фронт — `RoleBuilder.test.tsx`, `NotificationSettings.test.tsx`, `ReportPolicySettings.test.tsx`, `HRWorkspacePage.test.tsx`.

### Telegram-бот на тенанта, свои домены, учётка Telegram-пользователей (2026-09-30)
- **Свой бот у каждого тенанта** (подробно: `docs/multi-tenancy.md` §8, миграция `d4e8f1a2b3c9` после `b3c4d5e6f7a8`): таблица `tenant_telegram_bots` (токен шифруется `secret_box`, RLS). Handshake: Настройки → Автоматжуулалт ба интеграци → «Telegram бот» (`components/TenantTelegramBotSettings.tsx`) → `PUT /v1/tenant/telegram-bot` (`getMe`, `pending`) → админ открывает `t.me/<bot>?start=oyuns-<code>` → `app/bot/handshake_handlers.py` делает бот `active` и привязывает Telegram админа. Основной тенант продолжает работать на `BOT_TOKEN`, пока не подключит свой.
- **Бот-процесс мультибот** (`app/bot/main.py`, `BotPool`): раз в 15 с перечитывает реестр (`services/telegram_bots.py`), свой `getUpdates` на каждый бот, `dp.feed_update(..., bot_tenant_id=)`. Middleware оборачивает хендлер в `tenant_scope(tenant бота)`; работник другого тенанта в чужом боте не распознаётся. Отправка — `_make_bot(org)`/`send_telegram` (только `active`-боты; без бота Telegram-копия не шлётся), outbox маршрутизируется по задаче/уведомлению/получателю. Mini App: `verify_tenant_init_data` (подпись любого бота → тенант). Дайджест руководителя и сарын AI хураангуй — per tenant (`monthly_report_digests.organization_id`).
- **`manager_settings` per tenant** (`organization_id` замаплен, `/manager-settings` больше не legacy-only). UI «Удирдлагын телеграм мэдэгдлийн тохиргоо» переписан на Astryx: только числовые Telegram ID (username убран), выбор из работников с Telegram (`GET /manager-settings/recipient-options`, должность/роль/отдел). `MANAGER_TG_ID` — фолбэк только основного тенанта.
- **Telegram ID работника** вводится только при `active`-боте (`telegram_bot_connected` в `/v1/tenant/context`, иначе поле неактивно; API → 409 `telegram_bot_not_connected`). HR-инвайт ведёт в бот тенанта; без бота работник создаётся без инвайта (раньше `create_invite` падал 503 без `TELEGRAM_BOT_USERNAME`).
- **Свои домены через Cloudflare for SaaS** (§9, `services/custom_domains.py`, UI Настройки → Байгууллага → «Өөрийн домэйн», `components/TenantDomainSettings.tsx`, API `/v1/tenant/domains`): custom hostname в зоне `CLOUDFLARE_ZONE_ID`, клиент делает CNAME на `CLOUDFLARE_CNAME_TARGET` (+ TXT), `verified_at` ставится когда hostname и сертификат `active` (джоб `refresh_custom_domains` в боте, 5 мин). ⚠️ Нужен catch-all роутер Traefik на frontend (см. §9), иначе запросы с чужим Host не дойдут.
- **Логин/пароль Telegram-пользователей:** access-токен несёт `amr` (способ входа); Telegram-сессия меняет нэвтрэх нэр и нууц үг без текущего пароля, текущая сессия не разлогинивается. `requires_password_setup` = только `must_change_password` (раньше любая активная Telegram-сессия блокировала смену логина навсегда).
- **UI:** все секции админ-настроек свёрнуты по умолчанию (`SettingsSection` без `defaultOpen`, брендинг/лиценз/модули/домены тоже в секциях). Диалоги консоли (`Шинэ байгууллага`, лиценз, багц) прокручиваются — `components/DialogScrollBody.tsx` (Astryx `Dialog` клипует контент по `maxHeight`, кнопки вынесены из скролла).
- **Тесты:** `test_tenant_telegram_bots.py`, `test_bot_runner.py`, `test_custom_domains.py`, `test_manager_settings_tenant.py`, `test_profile_credentials.py`; фронт — `TenantTelegramBotSettings.test.tsx`, `TenantDomainSettings.test.tsx`, `ManagerSettingsPage.test.tsx`, `AdministrationSettingsPages.test.tsx`.

### Вкладка «Өнөөдөр» — холст виджетов (2026-10-01)
- **Страница** `pages/EnterpriseDashboardPage.tsx` = холст `components/today/`: `gridEngine.ts` (чистые функции, 12 колонок, вертикальная гравитация, push-down + swap, `normalizeLayout`, `findFreeSpot`, `nudgeVertical`), `TodayCanvas.tsx` (не знает о виджетах: pointer-drag через rAF + `translate3d`, ресайз за угол, long-press 450 мс → режим правки, клавиатура: стрелки/Shift+стрелки/Delete, автоскролл у края, imperative API `previewExternal/dropExternal` для drop из библиотеки; ширина < 720px → колонка, порядок стрелками ↑↓), `registry.tsx` (**новый виджет = одна запись** в `WIDGETS`: размер, лимиты, категория, `SettingsForm`, `allowMultiple`, `isAvailable`), `WidgetLibrary.tsx` (немодальный drawer, поиск, категории, drag на холст или «+»), `WidgetSettingsDialog.tsx` (Astryx Dialog: форма виджета + размер в ячейках).
- **Виджеты** (`components/today/widgets/`): world-clock (компактная полоса `WorldClockStrip`, без заголовка), worktime, kpi / kpi-single (период [Энэ / Өмнөх долоо хоног] — в настройках виджета; глобальный `TimePeriodFilter` со страницы убран), quick-actions (те же гейты, что в сайдбаре; поиск/AI открываются событиями `platform/app-events.ts`), tasks (включая вкладку «Байгууллага»/`scope=oversight`), news, mini-calendar, checkin (**по умолчанию скрыт**), timer, notes. Заголовки «Байгууллагын тойм» / «Нийт гүйцэтгэлийн үзүүлэлт» удалены.
- **Сохранение:** `GET/PUT /v1/auth/preferences/today-layout` (`user_accounts.preferences["today_layout"]`, без миграции; `widgets: null` = раскладка по умолчанию; ≤40 виджетов, settings ≤16 КБ) + кэш `localStorage` `oyuns.today-layout:<account>`; PUT с debounce 700 мс, побеждает более новый `updated_at`. Заметки — в settings виджета (≤4000 символов), состояние таймера — в `localStorage`.
- **Новости (модуль публикации):** `/v1/announcements` (`routers/announcements.py`, модель `models/announcements.py`, миграция `4a6e0c2d8b15` после `a9b8c7d6e5f4`, RLS). `GET ""` — опубликованная лента всем (контракт `Announcement` в `api/today.ts`); `GET /manage`, `POST`, `PATCH/DELETE /{id}`, `POST /images` — admin/manager/team_lead (admin/manager правят и закрепляют любые посты, team_lead — только свои, без «Онцлох»). Статусы `draft|published|archived`, `published_at` ставится при первой публикации. Картинки (`services/announcement_media.py`): PNG/JPEG/WebP ≤8 МБ, перекодируются (EXIF срезается, ≤2400px), лежат в `ANNOUNCEMENT_IMAGE_DIR` (внутри тома attachments), отдаются без авторизации по неугадываемому имени `GET /media/{name}` (как аватары); `cover_url`/`image_urls` принимают только такие URL. UI: `/announcements` (`pages/AnnouncementsPage.tsx`, Astryx; вход — иконка в шапке виджета новостей), редактор `components/announcements/` — Markdown-тулбар (`markdownEditing.ts`) + предпросмотр, обложка и галерея (≤12). Уведомления о новой публикации не рассылаются.
- **Тесты:** `gridEngine.test.ts`, `TodayCanvas.test.tsx`, `EnterpriseDashboardPage.test.tsx`, `WorldClockWidget.test.tsx`, e2e `e2e/today-canvas.spec.ts` (desktop: drag/resize/drop из библиотеки/настройки/тёмная тема; mobile: колонка), backend `test_today_layout_preferences.py`, `test_announcements.py`; фронт — `AnnouncementsPage.test.tsx`, `announcements/markdownEditing.test.ts`.

### Telegram-бот как компаньон ERP: роли из ERP, гейт незарегистрированных (2026-10-01)
- **Классификация каждого апдейта** (`app/bot/middlewares.py`): бот → тенант (нет тенанта → отказ `BOT_NOT_CONNECTED`, системный контекст больше не используется); Telegram ID → работник этого тенанта. Незарегистрированный или работник другого тенанта получает информационное сообщение (имя организации, свой Telegram ID, «обратитесь к ERP-админу/HR»; для `pending`-бота — «бот не до конца подключён»), хендлеры не запускаются. Исключения: `/start invite_…`, `/start oyuns-…` (handshake), `/myid`.
- **Роли — только из ERP:** middleware вызывает `actor_from_telegram_id` (прямые `RoleAssignment` + кастомные роли конструктора, напрямую и через команду) и кладёт `actor`, `roles`, `is_manager` в данные хендлера. `is_manager` = `TELEGRAM_MANAGEMENT_ROLES` (`admin`, `manager`; `app/core/roles.py`). Telegram-allowlist `manager_settings`/`MANAGER_TG_ID` **больше не даёт прав** ни в боте, ни в Mini App (`_miniapp_actor`) — это только список получателей уведомлений. `MANAGER_TG_ID` без значения по умолчанию (в коде, `docker-compose.yml`, `.env.example`).
- **Меню:** дефолтное (сотрудник) ставится при старте polling; меню руководителя — на приватный чат по текущей роли (`menu.sync_chat_menu`, обновляется на следующем сообщении после смены роли). Не-основным тенантам check-in команды не показываются; `/test_*` и `/seed_monthly_digest` убраны из меню (хендлеры остались).
- **Изоляция:** бот-процесс теперь вызывает `install_tenant_guards()` (раньше ORM-guard и `app.tenant_id` работали только в API). `reset_test_reports` и мутации задач (`set_status`/`snooze`/`submit_for_review`/`mark_overdue_pinged`) ограничены тенантом. Автопривязка по `@username` (бот и Mini App) — только к профилю без Telegram ID.
- **Не сделано:** джобы планировщика по-прежнему в системном контексте; дайджест руководителя для всех тенантов идёт по времени основного.
- **Тесты:** `test_tenant_telegram_bots.py`, `test_bot_menu.py`, `test_work_report_handlers.py`.

### OYUNS AI Agent v2 (2026-09-28, ветка `feature/oyuns-agent-v2`)
- **Поток:** запрос → `AIGateway.execute_turn` собирает контекст (кто спрашивает, роли, отдел, время/TZ, снимок: мои задачи/просрочки/отметка времени, `AVAILABLE_DATA`, preflight-знания, `PREVIOUS_RESULTS`) → **один** цикл OpenAI Responses со всеми разрешёнными `oyuns_*` инструментами → ответ. **Jev (jev-router) удалён**, LLM-роутер и keyword-классификация тоже; web_search только опциональный инструмент (никогда `tool_choice`). Превью задач видны всем с `assistant.preview`. Self-meeting fast path (`is_simple_self_meeting`) снова работает без модели.
- **Данные (`services/mcp/company_data.py`):** `oyuns_reports_search`, `oyuns_worktime_get`, `oyuns_hr_get`, `oyuns_crm_search`, `oyuns_contracts_search`, `oyuns_payroll_summary` (admin/hr + ERP-capability `payroll.view`; скрыт в групповых чатах через `sensitive_allowed=False`), `oyuns_projects_search(entity="ideas")`. Скоупы переиспользуют правила страниц (`chat_share_service`, `worktime_report_service._employee_query`, функции `app.hr.router`, CRM-роуты). Конверт MCP вырезает все `id`/`*_id`.
- **Модель и ключ — в настройках платформы** (`/administration/ai/knowledge`, только admin): `organization.settings["ai_agent"]` (ключ шифруется `secret_box`), API `/v1/settings/ai-agent` (`GET`/`PUT`/`GET /models`/`POST /test`), резолвер `services/ai_gateway/runtime.py` (org → env `OPENAI_API_KEY`, кэш 60 с). Модели выбираются из `/v1/models` или вводятся вручную; для 400 от кастомной модели — повтор с минимальным payload.
- **Права доступа AI-ассистента** (Настройки → OYUNS AI → «AI туслахын хандах эрх», `components/AiAccessSettings.tsx`, только admin): матрица раздел × «Унших»/«Үүсгэх ба засах» в `organization.settings["ai_agent"]["access"]`, API `GET/PUT /v1/settings/ai-agent/access`. Разделы и привязка к `oyuns_*` — `services/ai_gateway/access_policy.py` (тест требует, чтобы каждый инструмент каталога был ровно в одном разделе). Политика только **сужает** права пользователя; не настроенный раздел = разрешён. Применяется в `AIRuntime.access`: список инструментов модели/`AVAILABLE_DATA`/снимок/preflight-знания/fast-path превью задач/голос + повторная проверка в `ToolRegistry.dispatch_tool`. Кэш runtime 60 с — бот подхватывает изменения с задержкой до минуты.
- **Память:** дайджест результатов инструментов (заголовки + opaque refs) в `AssistantConversation.mcp_context` для follow-up вопросов.
- **Telegram:** голос/аудио/кружок → Chimege STT (фолбэк OpenAI) → тот же агент с `input_mode="voice"` → текст + Chimege TTS (если включено, не для превью задач). Reply на сообщение передаётся агенту как контекст. Markdown модели → Telegram HTML с фолбэком на plain.
- **Оценка:** `python -m scripts.oyuns_eval --email <account>` (живые промпты mn/ru/en, нужен ключ). DB-тесты: `tests/test_oyuns_agent_tools_db.py` (`SHARE_TEST_DATABASE_URL`).
- **Удалено:** `services/assistant_ai.py`, мёртвый legacy-роутер в `bot/assistant_handlers.py`, `enterprise_tools.run_agent`/`tool_specs`/`_offline_route`, `jev-router/`, корневой `package.json`. После деплоя убрать `JEV_*`/`TYPESAFE_*` из env Dokploy.

### Режимы Manager/Member, политика отчётов, голосовой звонок OYUNS (2026-09-28, ветка `claude/elegant-goodall-hhx8kn`)
- **Режим просмотра — серверный:** фронт шлёт `X-Workspace-Mode` с каждым запросом (`api/client.ts`, режим помнится в `localStorage`). `get_actor` → `apply_workspace_mode`: в `member` у admin/manager/team_lead роли сужаются до `member` (снимаются admin/manager/team_lead/hr/client_auditor), поэтому **все** страницы и API (отчёты, задачи, календарь, статистика, навигация, `RequireRoles`) показывают только своё. Реальные роли — `ActorContext.granted_roles`; `/v1/auth/me` отдаёт `roles` (эффективные) + `account_roles` + `workspace_mode`. Переключатель режима использует `get_account_actor` (без сужения), иначе из member нельзя вернуться. Смена режима инвалидирует все запросы. Manager-режим = полный объём по роли (договоры по-прежнему только admin/автор/ревьюер).
- **Политика отчётов** (`services/report_policy.py`, `organization.settings["report_policy"]`, `GET/PUT /v1/settings/report-policy`, PUT — admin; UI: Настройки → «Ажлын цаг ба процесс» → «Тайлангийн тохиргоо», `components/ReportPolicySettings.tsx`): частоты сотрудников `daily/weekly/monthly/quarterly/yearly/custom:<id>` (несколько сразу), кастомные периоды (каждые N дней/недель/месяцев от якорной даты), правила по отделам (переопределение частот сотрудников + **отчёт отдела**, пишет `Department.manager_employee_id`), `reminder_days`. Без настройки — прежнее поведение (daily + monthly).
- **Модель:** миграция `e5f6a7b8c9d0` — `work_reports.period_end`, `period_key` (id кастомного периода, `''` иначе), `department_id`; новые типы в `ck_work_reports_type`; `uq_work_report_period` заменён двумя частичными уникальными индексами (личные / отдела). Личные выборки обязаны фильтровать `department_id IS NULL`.
- **Автоматизация:** джоб `monthly_report_{emp}` теперь `send_periodic_report_prompts` — создаёт отчёт и шлёт напоминание в последние `reminder_days` периода (для недели не больше половины периода) по всем включённым частотам + отчётам отделов; daily-промпты/напоминания отключаются, если daily не включён. Веб: `GET /v1/reports/options` (что можно создать), `POST /v1/reports` проверяет политику и привязывает дату к периоду, список для сотрудника скрывает невключённые `awaiting`-типы, утверждение/reopen — для всех периодических типов.
- **Голосовой звонок OYUNS** (кнопка 📞 в чате с OYUNS Agent, `components/OyunsVoiceCall.tsx`): `POST /v1/assistant/voice/session` (`routers/assistant_voice.py`, `services/ai_gateway/voice_call.py`) выпускает эфемерный client secret OpenAI Realtime (`/v1/realtime/client_secrets`, TTL 120 с, ключ организации не уходит в браузер) с инструкциями OYUNS + тем же контекстом, что у чат-агента, и **только read-only** `oyuns_*` инструментами. Браузер соединяется по WebRTC (`/v1/realtime/calls`), вызовы инструментов идут через `POST /v1/assistant/voice/tool` с повторной проверкой прав. Модель/голос/вкл-выкл — в настройках AI (`realtime_model`, по умолчанию `gpt-realtime`; `realtime_voice`, по умолчанию `marin`; `realtime_enabled`). Лимит 10 сессий/10 мин на аккаунт.
- **Язык звонка и монгольский режим (Chimege):** фронт шлёт `language` = язык интерфейса (`i18n.language`) в `POST /voice/session`; звонок начинается на нём (фолбэк — `account.locale`, затем `mn`). Приветствие отправляется system-item'ом + `response.create` — **не** через `response.instructions` (оно заменяет инструкции сессии, из-за этого модель здоровалась на случайном языке). Realtime плохо понимает/говорит по-монгольски, поэтому при `language=mn` и готовом Chimege сессия отдаёт `mode="chimege"`: браузер сам детектит конец фразы (`components/chimegeCall.ts`, WAV 16 кГц) → `POST /voice/chimege/turn` (Chimege STT → `execute_turn(input_mode="voice_call")`, только read-only инструменты) → `POST /voice/chimege/speech` (Chimege TTS по предложениям). Состояние звонка (история + memory) хранится в памяти процесса API (один uvicorn-воркер), истекает после 30 мин простоя.
- **Токены Chimege в настройках** (Настройки → OYUNS AI → карточка «Chimege · Монгол яриа», `components/ChimegeSettings.tsx`): `chimege_stt_token_enc`/`chimege_tts_token_enc` (шифруются `secret_box`, наружу только last4) в `organization.settings["ai_agent"]`, env `CHIMEGE_API_TOKEN`/`CHIMEGE_TTS_API_TOKEN` — фолбэк. Переключатели `chimege_stt_enabled`, `chimege_tts_enabled`, `chimege_voice_call_enabled` (по умолчанию все `true`). Используются в Telegram-голосе, `/voice/transcriptions`, `/assistant/speech` и звонках (`runtime.chimege_tokens()`). `POST /v1/settings/ai-agent/chimege/test` синтезирует фразу и распознаёт её обратно.
- **Движок звонка + ElevenLabs** (2026-09-29): `ai_agent.voice_call_provider` = `auto|openai|chimege|elevenlabs` (Настройки → OYUNS AI → «Дуудлагын хөдөлгүүр»; `auto` = Chimege для `mn`, иначе OpenAI Realtime). В окне звонка переключатель движков (`providers` из `/voice/session`, выбор помнится в `localStorage` `oyuns.voiceProvider`, смена перезапускает звонок); не готовый движок → `resolve_provider` откатывается на авто. ElevenLabs (`services/elevenlabs_service.py`, карточка `components/ElevenLabsSettings.tsx`): ключ `elevenlabs_api_key_enc` (env `ELEVENLABS_API_KEY`), `elevenlabs_voice_id` (по умолчанию Sarah), `elevenlabs_model` (`eleven_flash_v2_5`/`turbo_v2_5`/`multilingual_v2`, v3 не стримит), `elevenlabs_enabled`. Пайплайн пошаговый, как Chimege: VAD в браузере → `POST /voice/turn` (Scribe `scribe_v2`, язык вне mn/ru/en → повтор с языком звонка; сбой → Chimege/OpenAI STT) → агент → ответ стримится браузером напрямую из `wss://api.elevenlabs.io/.../stream-input` (PCM 24 кГц, `components/elevenlabsCall.ts`) по одноразовому токену (`/v1/single-use-token/tts_websocket`, URL в ответе `/session`, `/turn` или `POST /voice/elevenlabs/stream`, не больше 200 на звонок). Ключ отклонён при старте → звонок идёт на авто-движке с `notice`. `/voice/chimege/turn` — алиас `/voice/turn`. ElevenLabs официально не поддерживает монгольский.
- **Тесты:** `test_workspace_mode_scope.py`, `test_report_policy.py`, `test_assistant_voice.py`, DB — `test_report_policy_db.py` (`SHARE_TEST_DATABASE_URL`); фронт — `WorkspaceModeProvider.test.tsx`, `ReportPolicySettings.test.tsx`, `ChatCallHeader.test.tsx`.

### ERP без хаба (2026-09-29, ветка `claude/vibrant-gates-o05ija`)
- **Пункта «ERP» в навбаре больше нет**, страница `ERPWorkspacePage` удалена; `/erp` → редирект на Настройки → «Модуль ба боломжууд» (`components/ERPModuleSettings.tsx`, Astryx). Каждый включённый модуль сам добавляет свой пункт меню (CRM, Төсөв, Payroll; «Данс» — по capability `accounts.view`).
- **Переключаемые модули — только `crm`/`budget`/`payroll`** (`ERP_MODULES` в `app/erp/service.py`); старые строки `erp_module_configs` для selling/buying/stock/… игнорируются в `/meta`. Удалены: KPI-дашборд (`/reports/dashboard`, `/reports/stock-balance`), master-data requests (`/master-requests/*`, master-операции в каталоге форм), phase-5 gate (`/admin/phase5/acceptance`), эндпоинты manufacturing/stock/assets. Таблицы БД не трогали (без destructive-миграции). Ядро учёта (документы, GL, счета, импорт) осталось — на нём payroll-проводки и AI-инструменты.

### Модуль «Төсөв, гүйцэтгэл» (бюджет, Dayansoft d161, 2026-09-29)
- Подробности: [`docs/budget-module.md`](docs/budget-module.md). Бэкенд `app/budget/` → `/v1/erp/budget`, модели `app/models/budget.py`, миграция `f6a7b8c9d0e1` (после `e5f6a7b8c9d0`). UI `/erp/budget` (список + редактор `/erp/budget/:id`), `/erp/budget/analysis`, `/erp/budget/accounts` — на Astryx.
- **Знак:** доход `+`, ББӨ/расходы `−` (иначе `422 budget_sign_mismatch`); факт = `credit − debit` по GL на связанных счетах. Поэтому `variance = actual − expected ≥ 0` всегда «хорошо». «Байх ёстой» — пропорция по дням до as-of.
- Один счёт плана счетов → максимум один бюджетный счёт (`uq_budget_account_links_org_erp_account`). Доступ — ERP capabilities `budget` / `budget_settings` (Accountant, admin; manager/team_lead — view/create/edit через bridge), модуль-тоггл `budget` только для навигации.
- Тесты: `test_budget_contract.py`, DB — `test_budget_db.py` (`BUDGET_TEST_DATABASE_URL`), фронт — `BudgetWorkspacePage.test.tsx`. ⚠️ В Astryx Table два закреплённых end-столбца дают щель — закрепляем один (действия строки в меню «⋯»).

### Дансны төлөвлөгөө (план счетов, Dayansoft d047, 2026-09-29)
- **UI `/erp/accounts`** (`pages/ChartOfAccountsPage.tsx`, Astryx): дерево счетов (группа → подсчета), фильтры по классу/статусу, «Ашиглалт» (где используется счёт), диалог создания/редактирования с банковскими реквизитами для `cash`/`bank`. Пункт меню «Данс» — по ERP capability `accounts.view` (admin, Accountant; manager/team_lead через bridge). Ссылки из ERP, настроек зарплаты и «Төсөвт данс».
- **Правила — `app/erp/chart.py`:** каталог `PURPOSES` (purpose → допустимые классы, модуль, posting `account_type`). **`account_type` всегда выводится из purpose** (`posting_type`), клиент его не задаёт — раньше create/update писали туда класс, и переименованная «Касс» переставала находиться `default_account("cash")`. CSV/ERPNext-импорт — `classify_import`. Родитель: только активная группа того же класса, без циклов. Использованный счёт: код/класс/purpose/валюта/is_group заблокированы (409 `erp_account_referenced_fields_locked` с `fields`), удаление → архив. API: `GET /v1/erp/accounting/accounts/catalog`, `GET …/accounts/usage` (по модулям: ledger/documents/parties/tax/settings/budget/payroll/children).
- **Сид на монгольском** (`DEFAULT_ACCOUNTS`), миграции `a1c2e3g4i5k6` (после `f6a7b8c9d0e1`, уже в `master`: банковские колонки + первая починка) → `c2d3e4f5a6b7` (договоры) → `f7a8b9c0d1e2` (только данные, идемпотентна: итоговые posting-типы, в т.ч. `accumulated_depreciation`/`advance_clearing`/`depreciation_expense`). Переименование сид-счетов, если имя ещё английское (переименованные организацией не трогаются), починка `account_type`/purpose у старых и импортированных строк.
- **Согласованность:** зарплатные настройки (`/erp/payroll/monthly/settings`) принимают только счёт нужного класса (зарплата и НДШ работодателя — `expense`, аванс — `asset`), пикеры сгруппированы по классу с «Санал болгох» по purpose (`components/accounts/accountShared.tsx`). Бюджетный счёт предлагает только счета своего вида (доход → income, ББӨ/расход → expense).
- **Тесты:** `test_chart_of_accounts.py`, DB — `test_chart_of_accounts_db.py` (`CHART_TEST_DATABASE_URL`); фронт — `ChartOfAccountsPage.test.tsx`, `EnterpriseShell.test.tsx`.

### Цалингийн тохиргоо, архивын гэрээний мэдээлэл, «Цалин» (2026-09-29)
- **`/erp/payroll/monthly/settings`** перерисована на Astryx (`pages/monthly-payroll/Settings.tsx`): карточки по группам (Ерөнхий / Илүү цаг ба НДШ / Урьдчилгаа / Суутгал / Дансны холболт), `NumberInput` с единицами, адаптивный `Grid` вместо горизонтального `FormLayout` (тот не сворачивается на мобильном), основная кнопка «Тохиргоо хадгалах» активна только при изменениях + метка «Хадгалаагүй өөрчлөлт». Редактор правил — сворачиваемая карточка, календарь — сетка карточек-дней.
- **Счёт урьдчилгаа** (`advance_clearing_account_id`) может быть `asset` **или** `expense` (например, тот же «Цалингийн зардал»): `monthly_workflow.SETTINGS_ACCOUNT_CLASSIFICATIONS` теперь допускает набор классов; роль `advance_clearing` в проводках (`PAYROLL_GL_CLASSIFICATIONS`, `PAYROLL_ACCOUNT_ROLE_REQUIREMENTS`, `payroll_gl_classification_ok`) — тоже `asset`/`expense`. Пикер в `PayrollSetupHub` учитывает это.
- **Архив договоров (`/contracts/archive`)**: у записей архива есть блок «Гэрээний бүртгэл» в панели «Мэдээлэл» (`components/ContractArchiveRegistry.tsx`) — те же данные, что у договоров из 6-шагового процесса. `PATCH /v1/contract-archive/entries/{id}/registry` (admin/legal_counsel): для загруженных вручную файлов данные лежат в новых колонках `contract_archive_entries` (миграция `a8b9c0d1e2f3`), для подписанных договоров — на самом `contract_documents`. `GET /contract-archive/entries/{id}` отдаёт `registry` (`holder` = `entry|contract`). `ContractRegistryPatch` теперь принимает **все** поля реестра (не только номер/ссылки), так что и `PATCH /contracts/{public_id}/registry` дополняет старые договоры. Код уникален среди договоров и записей архива; группы с записями архива не удаляются.
- **«Payroll» → «Цалин»**: пункт меню, модуль ERP (`ERP_MODULES`), KPI на ERP-дашборде. **Дансны төлөвлөгөө**: убран заголовок/описание над таблицей, кнопка «Данс нэмэх» справа в строке фильтров.
- Тесты: `test_contract_registry_db.py::test_archived_contracts_can_be_completed_with_contract_data`, `test_chart_of_accounts_db.py` (урьдчилгаа как expense), фронт — `Settings.test.tsx`, `ContractArchiveRegistry.test.tsx`.

### Реестр договоров «Гэрээ бүртгэх» (Dayansoft d028, 2026-09-29)
- **Метаданные договора** (`contract_documents`, миграция `c2d3e4f5a6b7` после `a1c2e3g4i5k6`): `code` (внутренний код, уникален в org; пусто → продолжает нумерацию последнего кода `ГЭ-2026/015 → 016`, по умолчанию `CT-0001`; существующие договоры получили `CT-000N`), `contract_number` (официальный номер), `group_id` → `contract_groups` (иерархия, фильтр по группе включает подгруппы), `party_id` → `erp_parties` (CRM; толгой харилцагч = `parent_party_id`), `signed_on`, `quantity`/`unit_id`/`unit_price`/`amount`/`currency`, `penalty_pct`, `payment_term_id`, `note`, `is_active`, `links` (online/shared/path; online/shared только http(s)), `custom_fields` («Мета»). Логика — `services/contract_registry.py`.
- **API** (`routers/contracts.py`): поля в `POST/PATCH /v1/contracts`; `GET /contracts/registry-options` (группы, единицы, условия оплаты, `next_code`), `GET /contracts/party-options?q=` (минимальный lookup CRM: код/имя/головной), `POST/PATCH/DELETE /contracts/groups` (admin/legal_counsel; удалить можно только пустую), `PATCH /contracts/{id}/registry` (номер/активность/ссылки/мета/заметка в любом статусе — автор, admin, legal_counsel). Список: `party_id`, `group_id`, `active`, `date_from/date_to` (пересечение срока), поиск по коду/номеру/контрагенту, `view=registry` (все статусы). Ответы содержат `overdue_days`, `file_count`, имена связанных записей. Неактивные договоры не получают напоминаний о сроке.
- **UI:** блок «Гэрээний бүртгэл» в форме (`components/ContractRegistryFields.tsx`), карточка реестра в правой колонке деталки, фильтры списка, `/contracts?party=ID`; вкладка «Гэрээ» в карточке CRM-клиента. Расчёты по договору (авлага/өглөг, §6 d028) не реализованы — в GL нет измерения «договор».
- **Тесты:** `test_contracts_contract.py`, DB — `test_contract_registry_db.py` (`CONTRACT_TEST_DATABASE_URL`); фронт — `ContractsWorkspacePage.test.tsx`, `ContractRegistryFields.test.tsx`. Попутно исправлено: список договоров падал `TypeError` (позиционный `author_name`), create/patch отдавали 500 после коммита (ленивая загрузка `updated_at`).

### Мобильный веб как нативное приложение (2026-09-28)
- **≤800px:** сайдбар скрыт; app bar (аватар → профиль, заголовок, уведомления/поиск/AI), таб-бар из 5 пунктов, «Бусад» — bottom sheet `MobileMoreSheet.tsx` (свайп вниз закрывает; режим, тема, ажилтнууд, выход). Pull-to-refresh — `PullToRefresh.tsx` (рефетч активных запросов, не на `/chat`, отключается при `.drag-overlay`). Таб-бар прячется при `html.keyboard-open` (фокус в поле **и** сжатие `visualViewport` > 150px).
- **CSS:** мобильный слой — в конце `index.css` («Mobile-native layer»); detail-sheet/hr-drawer/`ui-modal`/assistant/workers/voice call — bottom sheets. ⚠️ `workspace-features.css` импортируется **после** `index.css` — при равной специфичности его правила побеждают, мобильные оверрайды для его классов писать с повышенной специфичностью.
- **PWA:** `public/manifest.webmanifest` + `public/icons/`, theme-color синхронизируется с темой (`main.tsx`). Тесты: `e2e/mobile-native.spec.ts`.

### Чат-шаринг и отчёты руководителя (2026-09-25, `29b8452`, в `master` и на проде)
- **Слэш-меню в чате** (`ChatWorkspacePage.tsx`): `/` открывает меню активных задач, планов, черновиков договоров и отчётов, группы + живой поиск (`GET /v1/chat/share-items`, `services/chat_share_service.py`). Список ограничен ролью **отправителя** (менеджмент — всё; остальные — свои: назначенные/созданные задачи, свои идеи планов, договоры где автор/ревьюер, свои отчёты; план компании виден всем). Выбор → `POST /v1/chat/conversations/{id}/share` → сообщение с `action.type='shared_item'` (снимок-карточка на момент отправки; `body` — текстовый fallback).
- **Доступ к ссылке проверяется на каждое чтение у получателя** (`reader_can_open` в `_message_out`): нет прав → `can_open=false` и без `target_url` («Танд нээх эрх байхгүй»). Карточка сама доступа не даёт. Правила зеркалят страницы (`_task_for_actor`, `_get_contract`: договор открывает только admin/автор/ревьюер).
- **Deep-link'и:** `/tasks?task=`, `/contracts/{public_id}`, `/reports?report=ID`, `/plans?month=YYYY-MM&item=ID|idea=ID`.
- **Отчёты admin/manager** (`routers/report_insights.py`, `services/report_insights_service.py`, префикс `/v1/report-insights`, `report_insights` регистрируется в `main.py`; team_lead **не** включён): `GET /scope`, `GET /export/preview`, `GET /export` (1 отчёт → `.md`, иначе ZIP с папками по работнику или отделу + `manifest.csv`), `POST /summary` (KPI + тексты отчётов → OYUNS; чат с `history`, промпты про прибыль/расходы/ROI/KPI). UI: кнопка «Татах ба AI хураангуй» на `/reports` (`components/ReportInsightsPanel.tsx`). Экспорт и сводки пишутся в аудит (`record_change`).
- **Ограничение:** прибыль/расходы/ROI берутся только из текста отчётов работников, данных ERP в сводке нет; модель обязана писать «в данных нет», а не выдумывать. Без AI — детерминированный fallback (`degraded=true`).
- **`AIGateway.generate_text`** — новый метод без tools для серверно собранного контекста.
- **Тесты:** `backend/tests/test_chat_share_and_report_insights_db.py` идёт только при `SHARE_TEST_DATABASE_URL` (одноразовая Postgres, напр. `postgresql+asyncpg://tracker@127.0.0.1:55432/share_test`); фронт — `ChatWorkspacePage.test.tsx`, `ReportInsightsPanel.test.tsx`. Локальный прогон backend: py3.11 venv через `uv`, env-заглушки `DATABASE_URL/SYNC_DATABASE_URL/SECRET_KEY/BOT_TOKEN`. Известные падения до этих изменений: 39 backend-тестов и `ContractsWorkspacePage.test.tsx › queues and uploads attachments…`.
- **UI-предпочтение:** новые экраны по требованию пользователя строить на Astryx (`@astryxdesign/core`, см. `frontend/AGENTS.md`); слэш-меню/карточки/панель отчётов сделаны на существующем CSS — переделать на Astryx, когда настройка Astryx будет влита в `master`.

### Чат-бейджи, импорт payroll, HR-статистика, QR/геолокация (2026-09-28)
- **Непрочитанное в чате:** страница чата подтверждает прочтение и при возврате на вкладку (`visibilitychange`/`focus`), бейдж гасится оптимистично (`useAcknowledgeChat.onMutate`), счётчик в навбаре — websocket + фолбэк-опрос 30 с. Бэкенд: сообщения до `visible_after_message_id` (повторно добавленный участник) не считаются непрочитанными, ack их тоже закрывает. Тест: `tests/test_chat_unread_db.py` (`SHARE_TEST_DATABASE_URL`).
- **Excel-шаблон payroll** (`payroll/monthly_input_template.py`): порядок колонок как в таблице бодолта (§7.1/§7.2), отделы, предзаполнен текущими значениями, скрытая строка ключей (строка 3). Импорт меняет только изменённые ячейки, шалтгаан по умолчанию «Excel оролт»; старый плоский шаблон тоже читается.
- **HR:** секция «Урилга ба профайл» удалена (повторной генерации Telegram-инвайта в UI больше нет). В боковой панели сотрудника для admin/hr/manager/team_lead — `EmployeeWorktimeStats` (период + CSV/Excel) между «Цалингийн тохиргоо» и «Платформын эрх».
- **⚠️ Gotcha — fixed-оверлеи внутри страниц:** анимация входа `.workspace-content > *` (`animation … both`) оставляет stacking context, и `position: fixed` + `z-index` уходит под sticky-хедер. Оверлеи/drawer'ы рендерить через `createPortal(…, document.body)` (так сделан HR drawer).
- **Payroll:** ячейка «Ажилласан цаг» — `WorkedHoursInfo` (Astryx HoverCard: hover — превью, клик — закрепить), разбивка по `inputs.day_lines`.
- **Способы отметки времени:** `organization.settings.worktime_methods = {qr_enabled, location_enabled}` (по умолчанию оба `true`), `GET/PUT /v1/settings/worktime-methods` (PUT — admin). QR выключен → `/worktime-qr/clock` и `display-token` отдают 403 `worktime_qr_disabled`, сканер на `/worktime` скрыт. Геолокация выключена при включённом QR → офисный старт только по QR (`worktime_location_disabled` в web и Telegram); оба выключены → офисный старт без проверки.

## Проект: история (Azure ACA, реактивирован 2026-05-31)

Проект пересоздан с нуля на Azure Container Apps после потери старого хоста `172.201.9.182` (был удалён 2026-05-27, БД утеряны). БД стартовала пустой; admin-пользователь засеивается автоматически из `ADMIN_EMAIL`/`ADMIN_PASSWORD` при старте backend.

### Расширение v2 — таск-менеджер (2026-05-31, ветка `feature/tasks-and-miniapp` — **влита в `master`**)

Поверх трекера ежедневных опросов добавлен модуль задач (опросы/streak/leaderboard сохранены — задачи их дополняют). Миграции: `c1a2b3d4e5f6` (tasks/task_comments), `d2e3f4a5b6c7` (политика уведомлений + `notification_outbox` + `tasks.overdue_pinged_at`).
- **Бот-команды:** `/task [@кто] что [когда]`, `/mytasks`, `/assigned`, `/done <id>`, `/snooze <id> <время>`, `/dashboard`, `/myid`. **Ролевое меню** (`bot/menu.py`, `set_my_commands` scope): сотрудник 6 / руководитель 12.
- **AI-постановка задач** (`services/task_ai.py`, OpenAI gpt-4o-mini, fallback на `task_parser`): routed intent → LLM формулирует → **черновик** с кнопками ✅/✏️/❌ (FSM `TaskDraft` в `tasks_handlers.py`) → ставит исполнителю. Сотрудник может ставить только себе, руководитель — любому; «поставь мне» → self-assign (детерминированный `_SELF_RE`-фолбэк). Руководитель без строки `Employee` создаётся через `task_service.ensure_employee` (без расписания опросов).
- **OYUNS All-In-One assistant:** свободный текст и голос теперь сходятся в `bot/assistant_handlers.py` после task/survey FSM-роутеров. `services/assistant_ai.py` классифицирует 5 intents (`DELEGATE_TASK`, `QUERY_MY_TASKS`, `PLAN_WORK`, `DISCOVER_CAPABILITIES`, `GENERAL_PRODUCTIVITY`) строгим JSON Schema; без LLM есть детерминированный fallback. Ответ совпадает с языком пользователя (mn/en/ru), голос получает краткий текст. Админ ведёт активные статьи `company_knowledge` через JWT CRUD `/knowledge`; бот получает до 5 релевантных статей через `knowledge_service.py`.
- **Архитектура бота почищена:** общий `get_session()`, `EmployeeMiddleware` (инъекция `employee`/`is_manager`, автопривязка `telegram_id` по username), `keyboards.py`, сводка опроса в `services/survey_service.py`.
- **Уведомления (enterprise):** `services/notification_policy.py` — тихие часы/рабочее окно (09:00–20:00 Пн–Пт по умолч., DST-safe `next_allowed`); конфиг в `manager_settings` (quiet_start/end, work_weekdays, morning/evening_digest_time, overdue_escalation_days, notifications_enabled). `services/digest_service.py` — утро/вечер сотруднику + утренний обзор+эскалация руководителю (пустые не шлём), per-employee cron в `rebuild_jobs` для всех активных. `services/reminder_service.py` — напоминания с clamp в окно; просрочка = 1 пинг исполнителю (`overdue_pinged_at`), эскалация через `overdue_escalation_days` раб. дней.
- **Outbox:** пуш о назначении из веб/Mini App пишется в `notification_outbox`; бот шлёт джобом `drain_notification_outbox` (1 мин); задачи из api догоняет `reconcile_task_reminders` (2 мин). APScheduler живёт ТОЛЬКО в боте.
- **REST API:** `routers/tasks.py` — admin `/api/tasks` (JWT) + Mini App `/api/miniapp/*` (Telegram initData, `core/telegram_auth.py`; ⚠️ `BOT_TOKEN` нужен и api, и боту).
- **Веб:** `/tasks` — канбан для админа. **Telegram Mini App:** `/tg` — вертикальный канбан (Просрочено/Открыто/В работе/Завершено), initData-auth. Кнопка меню бота → `/tg` через Bot API `setChatMenuButton`.
- **Сотрудники (`/employees`, `EmployeesPage.tsx`):** кнопка «Изм.» открывает модалку редактирования (ФИО / telegram_username / часовой пояс / статус), Telegram ID read-only; та же модалка переиспользуется для создания. Бэкенд — `PUT /employees/{id}` (поля name/telegram_username/timezone/is_active, `exclude_none`). ⚠️ У сотрудников **нет поля phone и нет логина/пароля** — в веб-панель логинится только admin (`admin_users`, email+пароль); сотрудники взаимодействуют только через Telegram-бота.
- **Руководитель:** `manager_settings.telegram_id=201374791` + env бота `MANAGER_TG_ID=201374791`; также заведён как `Employee` id=1 (без расписания — для self-assign).
- **Sentry:** подключён (коммит `c01fe7a`, `app/observability/sentry.py` — api+bot+frontend).
- **Hardening валидации ответов (PR [#3](https://github.com/bronxtc52/tracker_artur/pull/3), миграция `a7b8c9d0e1f2`, база `feature/tasks-and-miniapp`):** класс багов как Sentry #28 — обязательное поле в `*Out`-схеме ↔ nullable-колонка с только client-side `default=` без `server_default`/`NOT NULL` → `NULL` на seed/singleton/raw-insert валит сериализацию FastAPI `ResponseValidationError` (500). Захардено 10 колонок (`manager_settings.{weekly_summary_day,alerts_enabled,gamification_enabled,soft_mode_weeks}`, `employees.is_active`, `schedules.variant`, `questions.{options,is_required,sort_order}`, `tasks.priority`): миграция `backfill→server_default→NOT NULL` + зеркало в `models.py` + app-level `field_validator`/`or`-фолбэки. Образ с фиксом задеплоен в проде (ревизия `harden-nullcols-0014`, alembic head `a7b8c9d0e1f2`). PR #3 влит в `feature/tasks-and-miniapp`, оттуда в `master` через [PR #4](https://github.com/bronxtc52/tracker_artur/pull/4) (merge-commit `5d598cb`, 2026-05-31). `master` и прод согласованы. **⚠️ Gotcha:** в `models.py` нельзя писать `server_default=text(...)` — у `Question.text` есть колонка-атрибут `text`, затеняющая `sqlalchemy.text()` внутри тела класса (`'Column' object is not callable` на импорте). Используется алиас `from sqlalchemy.sql import text as sa_text`.
- **CRM (Харилцагч + Харилцаа холбоо, по Dayansoft d026/d027):** расширенный `erp_parties` + `crm_activities`, API `app/crm/` → `/v1/erp/crm`, UI `/erp/crm`, миграция `d1e2f3a4b5c6`, напоминания `services/crm_reminders.py` (джоб в боте). Доступ — ERP capabilities (`parties`, `crm_activity`, `crm_settings`; роль Sales), не системные роли. Подробности: [`docs/crm-module.md`](docs/crm-module.md).
- **Тесты:** `backend/tests/` (parser, telegram_auth, notification_policy, task_ai) — облачный прогон через `backend/Dockerfile.test` (`az acr build` → `python -m pytest`; локально pip на VM нет).

- _(Устарело, Azure ACA)_ **Resource group:** `rg-tracker-artur-prod-neu` (North Europe)
- **ACA environment:** `cae-tracker-artur-prod-neu` (default domain `wittyhill-ad6320ed.northeurope.azurecontainerapps.io`)
- **Apps:**
  - `ca-tracker-artur-web` — React/Vite + nginx, **external** ingress :80. `/api/`→backend по HTTPS:443 (см. `frontend/nginx.conf`).
  - `ca-tracker-artur-api` — FastAPI/uvicorn, **internal** ingress :8000. Alembic-миграции в `start.sh` при каждом старте.
  - `ca-tracker-artur-bot` — aiogram long-polling (`python -m app.bot.main`), без ingress, ровно 1 реплика (иначе дубль polling).
- **ACR:** `acrtrackerarturprod` → образы `tracker-artur/backend`, `tracker-artur/frontend`. Сборка: `az acr build -r acrtrackerarturprod -t tracker-artur/<svc>:latest ./<svc>`.
- **PostgreSQL:** `psql-tracker-artur-prod` (Flexible Server, PG16, B1ms, North Europe), база `sales_tracker`, юзер `trackeradmin`, **SSL required** (`?ssl=require` для asyncpg, `?sslmode=require` для psycopg2).
- **Домен:** **`tracker.adarasoft.com`** (CNAME→web FQDN + TXT `asuid.tracker` в зоне `adarasoft.com`/`dns-rg`) + managed SSL. _(Был `artur.adarasoft.com` до 2026-06-01 — заменён полностью: старые DNS-записи `artur`/`asuid.artur` и ACA-биндинг удалены.)_
- **Секреты:** [[reference-kv-bronxtc-dev]] namespace `tracker-artur--production--{POSTGRES-PASSWORD,SECRET-KEY,ADMIN-EMAIL,ADMIN-PASSWORD,DATABASE-URL,SYNC-DATABASE-URL,BOT-TOKEN}`. В ACA проброшены как app-secrets (не keyvaultref). Admin email — `admin@adarasoft.com`.
- **⚠️ `pushed != deployed`:** после `az acr build` тег `:latest` не создаёт новую ревизию web/bot — деплоить обновление по digest (`...@sha256:...`) либо с `--revision-suffix`, затем сверять `az containerapp revision list`.

**Ниже — историческая справка** (как работало на старом VM-хосте; команды против `172.201.9.182`/`tracker.vitamarine.kz` не выполнять — мертвы).

---

## Окружение (HISTORICAL — старый VM-хост удалён)

- **Сервер:** ~~172.201.9.182 (Azure, Ubuntu)~~ — DELETED 2026-05-27
- **Рабочая папка:** ~~`/home/sadmin/artur/sales-tracker/`~~ — была на удалённом сервере
- **Домен:** ~~https://tracker.vitamarine.kz~~ — устаревший, заменён на `tracker.adarasoft.com`
- **БД:** PostgreSQL 15, пользователь `tracker`, база `sales_tracker` — данные потеряны вместе с сервером

## Запуск и остановка

```bash
# Запустить все сервисы
docker compose up -d

# Остановить
docker compose down

# Перезапустить один сервис
docker compose restart backend

# Логи
docker compose logs backend --tail=50 -f
docker compose logs bot --tail=50 -f
```

## Деплой изменений

### Backend (Python/FastAPI)

```bash
cd /home/sadmin/artur/sales-tracker

# После изменения кода — пересобрать и перезапустить
docker compose build backend && docker compose up -d backend

# Проверить что поднялся
docker compose logs backend --tail=20
curl -s https://tracker.vitamarine.kz/api/health
```

### Frontend (React/Vite)

```bash
# После изменения кода — пересобрать и перезапустить
docker compose build frontend && docker compose up -d frontend

# Проверить
curl -s -o /dev/null -w "%{http_code}" https://tracker.vitamarine.kz/
```

### Bot (aiogram)

```bash
docker compose build bot && docker compose up -d bot
docker compose logs bot --tail=20
```

### Полный редеплой

```bash
docker compose down
docker compose build
docker compose up -d
```

## Миграции базы данных

```bash
# Создать новую миграцию (после изменения моделей)
docker compose run --rm backend alembic revision --autogenerate -m "описание изменений"

# Применить миграции
docker compose run --rm backend alembic upgrade head

# Откатить последнюю миграцию
docker compose run --rm backend alembic downgrade -1

# Статус миграций
docker compose run --rm backend alembic current
```

Миграции применяются автоматически через `start.sh` при каждом старте backend.
Если добавляешь новую миграцию — сначала пересобери образ (`docker compose build backend`), затем она применится при `docker compose up -d backend`.

## Подключение к базе данных

```bash
# Интерактивный psql
docker compose exec db psql -U tracker -d sales_tracker

# Выполнить SQL-запрос
docker compose exec db psql -U tracker -d sales_tracker -c "SELECT * FROM employees;"

# Полезные запросы
# Список сотрудников:
docker compose exec db psql -U tracker -d sales_tracker -c "SELECT id, name, telegram_id, is_active FROM employees;"

# Последние ответы:
docker compose exec db psql -U tracker -d sales_tracker -c "SELECT * FROM answers ORDER BY id DESC LIMIT 10;"

# Настройки менеджера:
docker compose exec db psql -U tracker -d sales_tracker -c "SELECT * FROM manager_settings;"
```

## Бэкап

### Создать бэкап БД

```bash
# Разовый дамп в файл с датой
docker compose exec -T db pg_dump -U tracker sales_tracker > /home/sadmin/backups/sales_tracker_$(date +%Y%m%d_%H%M).sql

# Создать папку если не существует
mkdir -p /home/sadmin/backups
```

### Автоматический бэкап (cron)

```bash
# Добавить в crontab (бэкап каждый день в 03:00)
crontab -e
# Добавить строку:
# 0 3 * * * cd /home/sadmin/artur/sales-tracker && docker compose exec -T db pg_dump -U tracker sales_tracker > /home/sadmin/backups/sales_tracker_$(date +\%Y\%m\%d).sql
```

### Восстановить из бэкапа

```bash
docker compose exec -T db psql -U tracker sales_tracker < /home/sadmin/backups/sales_tracker_YYYYMMDD_HHMM.sql
```

### Список бэкапов

```bash
ls -lh /home/sadmin/backups/
```

## Первичная установка с нуля

```bash
# 1. Клонировать репозиторий
git clone https://github.com/bronxtc52/tracker_artur.git sales-tracker
cd sales-tracker

# 2. Создать .env файл
cat > .env << 'EOF'
POSTGRES_PASSWORD=your-strong-db-password
DATABASE_URL=postgresql+asyncpg://tracker:your-strong-db-password@db:5432/sales_tracker
SYNC_DATABASE_URL=postgresql+psycopg2://tracker:your-strong-db-password@db:5432/sales_tracker

SECRET_KEY=замените-на-случайную-строку-минимум-32-символа
ACCESS_TOKEN_EXPIRE_HOURS=24

BOT_TOKEN=токен-от-botfather
MANAGER_TG_ID=telegram-id-руководителя

ADMIN_EMAIL=admin@company.ru
ADMIN_PASSWORD=сложный-пароль-для-панели
EOF

# 3. Сгенерировать надёжный SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"

# 4. Запустить — миграции и admin создаются автоматически
docker compose up -d

# 5. Проверить
docker compose ps
curl -s https://your-domain/api/health
```

## Nginx и SSL

```bash
# Конфиг nginx
/etc/nginx/sites-available/tracker.vitamarine.kz

# Проверить конфиг
nginx -t

# Перезагрузить nginx
systemctl reload nginx

# Обновить SSL сертификат (Let's Encrypt, автообновление)
certbot renew --dry-run
```

## Структура docker-compose

| Сервис | Образ | Внутренний порт | Внешний порт |
|--------|-------|-----------------|--------------|
| db | postgres:15 | 5432 | — (только внутри) |
| backend | ./backend | 8000 | 8010 |
| bot | ./backend | — | — |
| frontend | ./frontend | 80 | 3010 |

## Переменные окружения (.env)

| Переменная | Описание |
|-----------|----------|
| `POSTGRES_PASSWORD` | Пароль PostgreSQL |
| `DATABASE_URL` | asyncpg URL к PostgreSQL |
| `SYNC_DATABASE_URL` | psycopg2 URL (для Alembic и APScheduler) |
| `SECRET_KEY` | Ключ для подписи JWT (минимум 32 символа) |
| `ACCESS_TOKEN_EXPIRE_HOURS` | Срок жизни токена (default: 24) |
| `BOT_TOKEN` | Токен Telegram-бота |
| `MANAGER_TG_ID` | Telegram ID руководителя |
| `ADMIN_EMAIL` | Email admin-пользователя панели |
| `ADMIN_PASSWORD` | Пароль admin-пользователя панели |

## Частые проблемы

**Backend не запускается — ошибка подключения к БД**
```bash
# Убедиться что db healthy
docker compose ps
# Подождать и перезапустить
docker compose restart backend
```

**Бот не отвечает**
```bash
docker compose logs bot --tail=30
docker compose restart bot
```

**Миграция не применяется**
```bash
# Проверить текущее состояние
docker compose run --rm backend alembic current
# Посмотреть историю
docker compose run --rm backend alembic history
# Применить вручную (после пересборки образа)
docker compose run --rm backend alembic upgrade head
```

**Порт занят**
```bash
ss -tlnp | grep 8010
```

## Секреты

**Где искать:** Key Vault `kv-bronxtc-dev` (RG `bronxtc_group`, RBAC, northeurope). Namespace для этого репо — **`tracker-artur`** (с дефисом, не `tracker_artur` — Key Vault names не допускают подчёркивание; 8 секретов на 2026-05-27: BOT-TOKEN, ADMIN-EMAIL/PASSWORD, DATABASE-URL, SYNC-DATABASE-URL, SECRET-KEY, MANAGER-TG-ID, ACCESS-TOKEN-EXPIRE-HOURS).

```bash
az keyvault secret show --vault-name kv-bronxtc-dev --name tracker-artur--backend--<KEY> --query value -o tsv
az keyvault secret list --vault-name kv-bronxtc-dev --query "[?starts_with(name, 'tracker-artur--')].name" -o tsv
```

**Правило:** не выдумываю значения секретов, не прошу пользователя ввести вручную — **сначала проверяю vault**. Если в vault нужного ключа нет — спрашиваю пользователя где взять, а не придумываю.
