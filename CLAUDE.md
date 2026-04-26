# CLAUDE.md — Sales Tracker

Инструкции для Claude Code по работе с этим проектом.

## Окружение

- **Сервер:** 172.201.9.182 (Azure, Ubuntu)
- **Рабочая папка:** `/home/sadmin/artur/sales-tracker/`
- **Домен:** https://tracker.vitamarine.kz
- **БД:** PostgreSQL 15, пользователь `tracker`, база `sales_tracker`, пароль `secret`
- **Admin панель:** admin@company.ru / admin123

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
docker compose exec db pg_dump -U tracker sales_tracker > /home/sadmin/backups/sales_tracker_$(date +%Y%m%d_%H%M).sql

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
# Восстановить из дампа
docker compose exec -T db psql -U tracker sales_tracker < /home/sadmin/backups/sales_tracker_20260426.sql
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
POSTGRES_USER=tracker
POSTGRES_PASSWORD=secret
POSTGRES_DB=sales_tracker
DATABASE_URL=postgresql+asyncpg://tracker:secret@db:5432/sales_tracker
SECRET_KEY=замените-на-случайную-строку-минимум-32-символа
ACCESS_TOKEN_EXPIRE_HOURS=24
BOT_TOKEN=токен-от-botfather
MANAGER_TG_ID=telegram-id-руководителя
EOF

# 3. Запустить БД и применить миграции
docker compose up -d db
sleep 5
docker compose run --rm backend alembic upgrade head

# 4. Создать admin-пользователя
docker compose run --rm backend python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.security import hash_password
from app.models.models import AdminUser
from app.core.config import settings

async def create_admin():
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession)
    async with async_session() as s:
        s.add(AdminUser(email='admin@company.ru', password_hash=hash_password('admin123')))
        await s.commit()
    await engine.dispose()

asyncio.run(create_admin())
"

# 5. Запустить все сервисы
docker compose up -d

# 6. Проверить
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

## Переменные окружения backend

| Переменная | Описание |
|-----------|----------|
| `DATABASE_URL` | asyncpg URL к PostgreSQL |
| `SECRET_KEY` | Ключ для подписи JWT |
| `ACCESS_TOKEN_EXPIRE_HOURS` | Срок жизни токена (default: 24) |
| `BOT_TOKEN` | Токен Telegram-бота |
| `MANAGER_TG_ID` | Telegram ID руководителя |

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
```

**Порт занят**
```bash
# Найти что занимает порт
ss -tlnp | grep 8010
# Или
lsof -i :8010
```
