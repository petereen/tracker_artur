# Sales Tracker — Трекер активности отдела продаж

Платформа для ежедневного сбора метрик от менеджеров по продажам через Telegram-бот с веб-панелью для руководителя.

## Стек

| Слой | Технологии |
|------|-----------|
| Backend | FastAPI, SQLAlchemy 2.0 async, Alembic, PostgreSQL 15 |
| Auth | JWT (python-jose) + bcrypt |
| Telegram-бот | aiogram 3.x, FSM-опросы |
| Планировщик | APScheduler 3.x + SQLAlchemyJobStore |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS v3 |
| State | Zustand v5 (persist), TanStack Query v5 |
| Инфраструктура | Docker Compose, Nginx, Let's Encrypt SSL |

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
│             └── /onboarding/template
│
├── /       → React SPA (порт 3010)
│             ├── Dashboard   — KPI, графики, топ сотрудников
│             ├── Employees   — список, создание, редактирование
│             ├── Questions   — банк вопросов (макс. 5)
│             ├── Schedule    — расписание опросов
│             ├── Journal     — история ответов + экспорт CSV/Excel
│             ├── Manager     — настройки Telegram-интеграции
│             └── Onboarding  — шаблон приветствия
│
└── bot     → Telegram @Sales_tracker56318_bot
              ├── /start, /today, /my_stats, /leaderboard
              └── FSM-опрос → inline-кнопки → сводка
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

ADMIN_EMAIL=admin@company.ru
ADMIN_PASSWORD=your-admin-password
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
│       ├── pages/        # 7 страниц
│       └── store/        # Zustand auth store
└── docker-compose.yml
```

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Регистрация / главное меню |
| `/today` | Заполнить опрос за сегодня |
| `/my_stats` | Личная статистика и streak |
| `/leaderboard` | Топ-3 сотрудников |
| `/help` | Справка |
