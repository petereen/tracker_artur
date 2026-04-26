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
│             └── /onboarding
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

Создайте `.env` в корне:

```env
POSTGRES_USER=tracker
POSTGRES_PASSWORD=secret
POSTGRES_DB=sales_tracker
SECRET_KEY=your-secret-key-min-32-chars
BOT_TOKEN=your-telegram-bot-token
MANAGER_TG_ID=your-telegram-id
```

Запустите:

```bash
docker compose up -d
```

Создайте admin-пользователя:

```bash
docker compose exec backend python -c "
from app.core.database import sync_engine
from app.core.security import hash_password
from app.models.models import Base, AdminUser
from sqlalchemy.orm import Session
with Session(sync_engine) as s:
    s.add(AdminUser(email='admin@company.ru', password_hash=hash_password('admin123')))
    s.commit()
"
```

Панель управления: `http://localhost:3010`

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
