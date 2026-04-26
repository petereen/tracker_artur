# CLAUDE.md — Sales Tracker

Инструкции для Claude Code по работе с этим проектом.

## Окружение

- **Сервер:** 172.201.9.182 (Azure, Ubuntu)
- **Рабочая папка:** `/home/sadmin/artur/sales-tracker/`
- **Домен:** https://tracker.vitamarine.kz
- **БД:** PostgreSQL 15, пользователь `tracker`, база `sales_tracker`
- **Учётные данные:** хранятся в `.env` (не в репозитории)

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
