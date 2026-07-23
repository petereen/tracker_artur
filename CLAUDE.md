# CLAUDE.md — OYUNS All-In-One Corporate AI Assistant

Инструкции для Claude Code по работе с этим проектом.

> 📄 **Продуктовое ТЗ (описательное, без тех. стека)** — как работает сервис и как взаимодействуют бот, Telegram Mini App и веб-кабинет: [`docs/portal-spec.md`](docs/portal-spec.md). Ключевой принцип: три канала поверх единого ядра, веб-кабинет сотрудника = основа Mini App.

## ✅ Статус проекта: АКТИВЕН на Azure ACA (реактивирован 2026-05-31)

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
- **Тесты:** `backend/tests/` (parser, telegram_auth, notification_policy, task_ai) — облачный прогон через `backend/Dockerfile.test` (`az acr build` → `python -m pytest`; локально pip на VM нет).

- **Resource group:** `rg-tracker-artur-prod-neu` (North Europe)
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
