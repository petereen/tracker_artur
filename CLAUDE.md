# CLAUDE.md — OYUNS Agent

Инструкции для Claude Code по работе с этим проектом.

> 📄 **Продуктовое ТЗ (описательное, без тех. стека)** — как работает сервис и как взаимодействуют бот, Telegram Mini App и веб-кабинет: [`docs/portal-spec.md`](docs/portal-spec.md). Ключевой принцип: три канала поверх единого ядра, веб-кабинет сотрудника = основа Mini App.

## ✅ Статус проекта: АКТИВЕН на Dokploy (VPS) — `https://erp.oyuns.mn`

> **Прод = Dokploy на VPS** (`docker-compose.dokploy.yml`), API под `/api` (`/api/health`). **Деплой = push в `origin/master`** (github.com/petereen/tracker_artur): новые роуты появляются на проде через секунды после push. Проверка: незащищённый роут → `403` (есть) / `404` (нет), плюс смена хэша `assets/index-*.js`. CLI `az` локально не установлен.
> **Блок про Azure ACA ниже устарел** (исторический, актуальность не проверялась) — не использовать для деплоя. Раздел «Деплой изменений» с `docker compose` — тоже для локальной/старой схемы.
> **Рабочее дерево общее:** в нём параллельно правят другие люди/агенты. Коммить только свои hunk-и (`git apply --cached` с отфильтрованным патчем), проверять коммит в чистом `git worktree` (tsc + vitest + build + pytest) и только потом пушить в `master` (пуш = деплой, подтверждать у пользователя).

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

### Модуль «Төсөв, гүйцэтгэл» (бюджет, Dayansoft d161, 2026-09-29)
- Подробности: [`docs/budget-module.md`](docs/budget-module.md). Бэкенд `app/budget/` → `/v1/erp/budget`, модели `app/models/budget.py`, миграция `f6a7b8c9d0e1` (после `e5f6a7b8c9d0`). UI `/erp/budget` (список + редактор `/erp/budget/:id`), `/erp/budget/analysis`, `/erp/budget/accounts` — на Astryx.
- **Знак:** доход `+`, ББӨ/расходы `−` (иначе `422 budget_sign_mismatch`); факт = `credit − debit` по GL на связанных счетах. Поэтому `variance = actual − expected ≥ 0` всегда «хорошо». «Байх ёстой» — пропорция по дням до as-of.
- Один счёт плана счетов → максимум один бюджетный счёт (`uq_budget_account_links_org_erp_account`). Доступ — ERP capabilities `budget` / `budget_settings` (Accountant, admin; manager/team_lead — view/create/edit через bridge), модуль-тоггл `budget` только для навигации.
- Тесты: `test_budget_contract.py`, DB — `test_budget_db.py` (`BUDGET_TEST_DATABASE_URL`), фронт — `BudgetWorkspacePage.test.tsx`. ⚠️ В Astryx Table два закреплённых end-столбца дают щель — закрепляем один (действия строки в меню «⋯»).

### Дансны төлөвлөгөө (план счетов, Dayansoft d047, 2026-09-29)
- **UI `/erp/accounts`** (`pages/ChartOfAccountsPage.tsx`, Astryx): дерево счетов (группа → подсчета), фильтры по классу/статусу, «Ашиглалт» (где используется счёт), диалог создания/редактирования с банковскими реквизитами для `cash`/`bank`. Пункт меню «Данс» — по ERP capability `accounts.view` (admin, Accountant; manager/team_lead через bridge). Ссылки из ERP, настроек зарплаты и «Төсөвт данс».
- **Правила — `app/erp/chart.py`:** каталог `PURPOSES` (purpose → допустимые классы, модуль, posting `account_type`). **`account_type` всегда выводится из purpose** (`posting_type`), клиент его не задаёт — раньше create/update писали туда класс, и переименованная «Касс» переставала находиться `default_account("cash")`. CSV/ERPNext-импорт — `classify_import`. Родитель: только активная группа того же класса, без циклов. Использованный счёт: код/класс/purpose/валюта/is_group заблокированы (409 `erp_account_referenced_fields_locked` с `fields`), удаление → архив. API: `GET /v1/erp/accounting/accounts/catalog`, `GET …/accounts/usage` (по модулям: ledger/documents/parties/tax/settings/budget/payroll/children).
- **Сид на монгольском** (`DEFAULT_ACCOUNTS`), миграция `f7a8b9c0d1e2` (после `f6a7b8c9d0e1`): банковские колонки, переименование сид-счетов, если имя ещё английское (переименованные организацией не трогаются), починка `account_type`/purpose у старых и импортированных строк.
- **Согласованность:** зарплатные настройки (`/erp/payroll/monthly/settings`) принимают только счёт нужного класса (зарплата и НДШ работодателя — `expense`, аванс — `asset`), пикеры сгруппированы по классу с «Санал болгох» по purpose (`components/accounts/accountShared.tsx`). Бюджетный счёт предлагает только счета своего вида (доход → income, ББӨ/расход → expense).
- **Тесты:** `test_chart_of_accounts.py`, DB — `test_chart_of_accounts_db.py` (`CHART_TEST_DATABASE_URL`); фронт — `ChartOfAccountsPage.test.tsx`, `EnterpriseShell.test.tsx`.

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
