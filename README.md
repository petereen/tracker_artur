# OYUNS Agent

Корпоративный AI-ассистент для личной продуктивности, постановки и контроля задач, ответов по управляемой базе знаний и ежедневных опросов метрик — через Telegram-бота, веб-панель и Telegram Mini App. Прод: **https://tracker.adarasoft.com** (Azure Container Apps). Документы: [Политика конфиденциальности](https://tracker.adarasoft.com/privacy) · [Условия использования](https://tracker.adarasoft.com/terms).

## Стек

| Слой | Технологии |
|------|-----------|
| Backend | FastAPI, SQLAlchemy 2.0 async, Alembic, PostgreSQL 16 |
| Auth | JWT (python-jose) + bcrypt; Telegram `initData` (HMAC) для Mini App |
| Telegram-бот | aiogram 3.x, FSM (опросы + черновики задач), ролевое меню |
| Планировщик | APScheduler 3.x + SQLAlchemyJobStore (напоминания, дайджесты, эскалация) |
| AI | Chimege/OpenAI STT + строгие structured outputs для intent routing, планов и ответов, `dateparser` |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS v3 |
| State | Zustand v5 (persist), TanStack Query v5 |
| Mini App | Telegram WebApp (`/tg`) поверх того же SPA |
| Observability | Sentry (api + bot + frontend) |
| Хостинг | **Azure Container Apps** (web/api/bot) + PG Flexible; локально — Docker Compose |

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
              └── свободный текст/голос → intent router → обработчик
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

Создайте `.env` в корне (все переменные обязательны):

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
OPENAI_WHISPER_MODEL=gpt-4o-mini-transcribe
# Used when OPENAI_TRANSCRIBE_LANGUAGE was previously set to mn/mon.
OPENAI_MONGOLIAN_TRANSCRIBE_MODEL=gpt-4o-mini-transcribe
OPENAI_TASK_MODEL=gpt-4o-mini
# Optional; falls back to OPENAI_TASK_MODEL.
OPENAI_ASSISTANT_MODEL=
# Leave empty for Mongolian: Whisper detects it automatically.
OPENAI_TRANSCRIBE_LANGUAGE=

# Preferred provider for Mongolian voice tasks (optional).
# Obtain the token from console.chimege.com after activating the service.
CHIMEGE_API_TOKEN=your-chimege-api-token
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

Текстовые и голосовые сообщения проходят через единый intent router:

- `DELEGATE_TASK` — подтверждаемый черновик задачи; сотрудник ставит себе, руководитель — любому.
- `QUERY_MY_TASKS` — задачи, назначенные пользователю или созданные им, с фильтрами «сегодня», «эта неделя» и произвольным периодом.
- `PLAN_WORK` — план дня, time-boxing и разбиение сложной работы на шаги.
- `DISCOVER_CAPABILITIES` — динамическая справка по доступным функциям.
- `GENERAL_PRODUCTIVITY` — рабочие черновики, сводки и ответы по задачам и базе знаний компании.

Также доступны детерминированные запросы к справочнику сотрудников, например «Покажи список сотрудников». Бот показывает только рабочие поля: имя, `@username`, активность и роль руководителя; Telegram ID, учётные данные и ответы на опросы не раскрываются.

Ответ соответствует языку пользователя (монгольский, английский или русский; fallback — монгольский). Голос распознаётся в текст, а ответ остаётся коротким Telegram-текстом. Без `OPENAI_API_KEY` запросы задач, справка, детерминированная постановка и базовый план остаются доступны.

## База знаний компании

- Администратор управляет короткими статьями (заголовок, категория, содержание, активность) в разделе **«Компанийн мэдлэг»**.
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
