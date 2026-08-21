# OYUNS Agent

Корпоративный AI-ассистент для личной продуктивности, постановки и контроля задач, ответов по управляемой базе знаний и ежедневных опросов метрик — через Telegram-бота, веб-панель и Telegram Mini App. Прод: **https://erp.oyuns.mn** (Dokploy на VPS). Legacy admin: **https://artur.oyuns.mn**. Документы: [Политика конфиденциальности](https://erp.oyuns.mn/privacy) · [Условия использования](https://erp.oyuns.mn/terms).

## Стек

| Слой | Технологии |
|------|-----------|
| Backend | FastAPI, SQLAlchemy 2.0 async, Alembic, PostgreSQL 16 |
| Auth | JWT (python-jose) + bcrypt; Telegram OIDC/PKCE for browser/native login; signed `initData` (HMAC) for the Mini App |
| Telegram-бот | aiogram 3.x, FSM (опросы + черновики задач), ролевое меню |
| Планировщик | APScheduler 3.x + SQLAlchemyJobStore (напоминания, дайджесты, эскалация) |
| AI | Chimege/OpenAI STT + native function tools для routing + строгие structured outputs для планов и ответов, `dateparser` |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS v3 |
| State | Zustand v5 (persist), TanStack Query v5 |
| Mini App | Telegram WebApp (`/tg`) поверх того же SPA |
| Observability | Sentry (api + bot + frontend) |
| Хостинг | **Dokploy на VPS** (frontend/api/bot/PostgreSQL); локально — Docker Compose |

## Архитектура

```
tracker.vitamarine.kz
│
├── /api/   → FastAPI backend (порт 8010)
│             ├── /auth/login
│             ├── /employees
│             ├── /questions
│             ├── /schedules
│             ├── /manager-settings
│             ├── /dashboard/summary
│             ├── /answers + /answers/export
│             ├── /onboarding/template
│             └── /knowledge
│
├── /       → React SPA (порт 3010)
│             ├── Dashboard   — KPI, графики, топ сотрудников
│             ├── Employees   — список, создание, редактирование
│             ├── Questions   — банк вопросов (макс. 5)
│             ├── Schedule    — расписание опросов
│             ├── Journal     — история ответов + экспорт CSV/Excel
│             ├── Manager     — настройки Telegram-интеграции
│             ├── Knowledge   — управляемая база знаний OYUNS
│             └── Onboarding  — шаблон приветствия
│
└── bot     → Telegram @Sales_tracker56318_bot
              ├── команды, FSM-опросы и черновики задач
              └── свободный текст/голос → OpenAI tools → безопасный обработчик
```

## Быстрый старт

### Требования
- Docker + Docker Compose
- Telegram Bot Token (получить у @BotFather)

### Установка

```bash
git clone https://github.com/bronxtc52/tracker_artur.git
cd tracker_artur
```

Для локальной разработки скопируйте готовый безопасный шаблон (он создаёт admin-пользователя `admin` с паролем `admin12345`):

```bash
cp .env.local.example .env
```

Для production создайте `.env` вручную и замените локальные значения на секреты и HTTPS-адреса:

```env
POSTGRES_PASSWORD=your-strong-db-password
DATABASE_URL=postgresql+asyncpg://tracker:your-strong-db-password@db:5432/sales_tracker
SYNC_DATABASE_URL=postgresql+psycopg2://tracker:your-strong-db-password@db:5432/sales_tracker

SECRET_KEY=your-random-key-min-32-chars
BOT_TOKEN=your-telegram-bot-token
MANAGER_TG_ID=your-telegram-id
# Public HTTPS URL of the Mini App. The bot will show it as the “Самбар” button.
MINI_APP_URL=https://your-domain/tg

ADMIN_EMAIL=admin@company.ru
ADMIN_PASSWORD=your-admin-password

# Optional: enable voice input and AI assistance
OPENAI_API_KEY=your-openai-api-key
AI_REDIS_URL=redis://redis:6379/0
# Optional: validated JSON override for the GPT-5.6 routing registry.
AI_MODEL_REGISTRY_JSON=
# Required to answer live exchange-rate questions. Keep server-side only.
AGENT_RATES_API_KEY=your-agent-rates-api-key
OPENAI_WHISPER_MODEL=gpt-4o-mini-transcribe
# Used when OPENAI_TRANSCRIBE_LANGUAGE was previously set to mn/mon.
OPENAI_MONGOLIAN_TRANSCRIBE_MODEL=gpt-4o-mini-transcribe
OPENAI_TASK_MODEL=gpt-4o-mini
# Optional; falls back to OPENAI_TASK_MODEL.
OPENAI_ASSISTANT_MODEL=gpt-5.6-luna
# Leave empty for Mongolian: Whisper detects it automatically.
OPENAI_TRANSCRIBE_LANGUAGE=

# Optional separate Chimege credentials for voice input and spoken answers.
# Obtain each token from console.chimege.com after activating the service.
CHIMEGE_API_TOKEN=your-chimege-stt-token
CHIMEGE_TTS_API_TOKEN=your-chimege-tts-token
CHIMEGE_PUNCTUATE=true
```

Сгенерировать надёжный `SECRET_KEY`:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Запустите:

```bash
docker compose up -d
```

Локальная панель: `http://localhost:3010`. Войти можно как `admin` / `admin12345`.
Не используйте эти локальные учётные данные в production.

### Frontend development with hot reload

For immediate visual updates while editing React/CSS files, keep the Docker
backend and database running, then start Vite directly on the host:

```bash
docker compose up -d db backend
cd frontend
npm install
npm run dev -- --host 127.0.0.1
```

Open `http://localhost:5173`. Vite proxies `/api` to the Docker backend at
`http://localhost:8010`; edits are applied automatically without rebuilding
the frontend image. Use `Ctrl+C` to stop Vite.

### iOS, Android, and OTA releases

The same Vite/React source is wrapped by Capacitor 8 for `mn.oyuns.workspace` and distributed through iOS, Android, and the existing web deployment. Native push enrollment, secure native sessions, safe-area behavior, live reload, signing prerequisites, and self-hosted OYUNS OTA staging-to-production releases are documented in [docs/mobile-release.md](docs/mobile-release.md).

### Monthly report digest test

Run the isolated digest test with deterministic dummy reports:

```bash
cd backend
python -m pytest -q tests/test_monthly_report_digest.py
```

The test uses the real monthly digest orchestration and fallback summarizer,
but does not write reports to the database, call OpenAI, or send Telegram messages.

For a manual Telegram test, a manager can send `/seed_monthly_digest` first.
The bot creates approved `monthly_test` reports for all active employees.
Then send `/test_monthly_digest` to run the real digest logic and receive the
result in that manager chat.

Миграции и admin-пользователь создаются автоматически при первом запуске.

Панель управления: `https://your-domain` или `http://localhost:3010`

## Продуктовые правила

- Максимум **5 обязательных вопросов** на сотрудника
- Рейтинг — только **топ-3**, без антирейтинга
- Первая неделя — **мягкий режим**: напоминания только сотруднику
- Часовые пояса: время опроса привязано к часовому поясу сотрудника
- Все ответы хранятся бессрочно

## Структура проекта

```
sales-tracker/
├── backend/
│   ├── app/
│   │   ├── bot/          # Telegram-бот + планировщик
│   │   ├── core/         # config, database, security, deps
│   │   ├── models/       # SQLAlchemy модели
│   │   └── routers/      # FastAPI роутеры
│   ├── alembic/          # миграции БД
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── api/          # axios client + React Query hooks
│       ├── components/   # UI-компоненты (Card, Btn, Input, ...)
│       ├── pages/        # админ-панель, задачи, база знаний и Mini App
│       └── store/        # Zustand auth store
└── docker-compose.yml
```

## Команды бота

Меню **ролевое** (`set_my_commands` со scope): сотрудник видит базовый набор, руководитель — расширенный.

| Команда | Кому | Описание |
|---------|------|----------|
| `/start`, `/help`, `/myid` | все | регистрация / справка / свой Telegram ID |
| `/today`, `/my_stats`, `/leaderboard` | все | опрос за сегодня, статистика/streak, топ-3 |
| `/mytasks` | все | мои активные задачи |
| `/done <id>`, `/snooze <id> <время>` | все | завершить / перенести срок |
| `/task [@кто] что [когда]` | руководитель | поставить задачу (быстрый детерминированный путь) |
| `/assigned`, `/dashboard` | руководитель | что я поставил / сводный дашборд |
| `/summary`, `/week`, `/blockers` | руководитель | сводки по опросам |

## OYUNS: свободный текст и голос

Текстовые и голосовые сообщения проходят через единый OpenAI native tool router.
Модель выбирает не более одного строгого function tool (`parallel_tool_calls=false`):

- `create_task` — извлекает исполнителя, заголовок, приоритет и срок, после чего открывает существующий подтверждаемый черновик. Сам tool никогда не пишет задачу в БД.
- `get_my_tasks` — читает разрешённый workload текущего пользователя; с `purpose=plan` запускает планирование по этим задачам.
- `get_company_info` — читает активную базу знаний PostgreSQL или актуальный справочник сотрудников.
- Прямой текстовый ответ — только справка о возможностях, общая корпоративная помощь или мягкий отказ для запроса вне scope.

Внутренние обработчики по-прежнему используют безопасные категории `CREATE_TASK`,
`VIEW_MY_TASKS`, `COMPANY_INFO`, `AGENT_CAPABILITIES` и `UNKNOWN`. Строгие схемы
запрещают дополнительные аргументы; scope команды проверяется сервером, а не
моделью. Неясные запросы не создают задачу: они сохраняются в защищённую очередь
проверки без привязки к сотруднику. Администратор может просмотреть `GET /assistant-learning/unknown`,
отметить запись как проверенную или превратить подтверждённый ответ в активную
статью базы знаний через `POST /assistant-learning/unknown/{id}/promote`.

Также доступны детерминированные запросы к справочнику сотрудников, например «Покажи список сотрудников». Бот показывает только рабочие поля: имя, `@username`, активность и роль руководителя; Telegram ID, учётные данные и ответы на опросы не раскрываются.

Руководитель может поставить одинаковую задачу всем **активным** сотрудникам текстом или голосом: например, «Назначь встречу всем сотрудникам». Сначала показывается один черновик с количеством получателей; после подтверждения создаётся отдельная задача и уведомление для каждого сотрудника.

Ответ соответствует языку пользователя (монгольский, английский или русский; fallback — монгольский). Голос распознаётся в текст, а ответ остаётся коротким Telegram-текстом. Для успешного ответа OYUNS требуется `OPENAI_API_KEY`: при недоступности всех live-моделей сервис возвращает ошибку, а не локальный AI-ответ.

## AI gateway

OYUNS web и Telegram используют единый live gateway на Responses API. Отдельный
live-классификатор выбирает `simple_qa`, `complex_reasoning`,
`code_generation` или `multimodal`, затем маршрутизатор выбирает GPT-5.6 Luna,
Terra или Sol по конфигурации. Временные и явно проверяемые вопросы обязательно
включают native web search; запросы к корпоративным данным используют только
permission-scoped tools.

Redis хранит точные cache hits, PostgreSQL/pgvector — только безопасные
семантические hits для контекст-независимого simple QA. RAG, действия, история
диалога и web-search ответы не кэшируются. Значения TTL и similarity threshold
настраиваются через `AI_*` переменные; default TTL — 24 часа, threshold — 0.94.

Проверка с реальным ключом запускается только вручную:

```bash
cd backend
OPENAI_API_KEY=... python scripts/verify_ai_gateway_live.py
```

## База знаний компании

- Администратор управляет короткими статьями (заголовок, категория, содержание, активность) в разделе **«Компаний өгөгдлийн сан»**.
- Бот получает не более пяти релевантных активных статей и ограничивает их общий объём перед LLM-вызовом.
- Неактивные статьи не передаются боту. В текстовом ответе показываются названия использованных источников.
- Внешние документы, URL, векторный поиск и долговременная история диалога не используются.

## Задачи, уведомления и Mini App

- **Задачи** (`tasks`/`task_comments`) дополняют опросы: статусы `open/in_progress/done/overdue/cancelled`, приоритет, дедлайн, исполнитель/постановщик, комментарии.
- **Веб-канбан** `/tasks` (админ, JWT) и **Telegram Mini App** `/tg` (вертикальный канбан, авторизация по Telegram `initData`).
- **Открытие из бота:** после задания `MINI_APP_URL` бот добавляет постоянную кнопку **«Самбар»** и команду `/app`; руководитель видит все области задач в Mini App. Адрес должен быть доступен по HTTPS.
- **Политика уведомлений (enterprise):**
  - Тихие часы / рабочее окно (по умолч. **09:00–20:00, Пн–Пт**) — рутинные пуши вне окна **откладываются** на ближайшее начало рабочего дня (DST-safe).
  - **Дайджесты** (батчинг вместо спама): сотруднику — утро (на сегодня + просрочка) и вечер (остаток/закрытое); руководителю — утренний обзор по команде + эскалация. Пустые не отправляются.
  - **Напоминания** до дедлайна по `reminder_intervals_min` (по умолч. за сутки / за 2 ч / в момент), с clamp в рабочее окно.
  - **Просрочка:** 1 пинг исполнителю, эскалация руководителю — через `overdue_escalation_days` рабочих дней.
  - Конфиг политики — в `manager_settings` (`quiet_start/quiet_end/work_weekdays/morning_digest_time/evening_digest_time/overdue_escalation_days/notifications_enabled`).
- **Архитектура уведомлений:** APScheduler живёт в процессе **бота**; задачи/уведомления, созданные из веб/Mini App (процесс **api**), подхватываются джобами `reconcile_task_reminders` (2 мин) и `drain_notification_outbox` (1 мин, таблица `notification_outbox`).

## REST API (задачи)

- **Админ (JWT):** `GET/POST /api/tasks`, `GET/PATCH /api/tasks/{id}`, `GET/POST /api/tasks/{id}/comments`.
- **Mini App (`X-Telegram-Init-Data`):** `GET /api/miniapp/me`, `GET /api/miniapp/tasks?scope=&include_done=`, `POST /api/miniapp/tasks`, `PATCH /api/miniapp/tasks/{id}`.
- **База знаний (admin JWT):** `GET/POST /api/knowledge`, `PUT/DELETE /api/knowledge/{id}`.
