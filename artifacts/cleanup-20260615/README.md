# Teardown snapshot — 2026-06-15

Проект **tracker_artur** удалён безвозвратно по явной команде пользователя 2026-06-15
(«удали безвозвратно tracker_artur … хочу снести все», GitHub-репо оставлен как история).

Эта папка — финальный снимок конфигурации перед сносом resource group
`rg-tracker-artur-prod-neu` (northeurope).

## Что удалено
- RG `rg-tracker-artur-prod-neu` целиком: ACR `acrtrackerarturprod`, ACA env
  `cae-tracker-artur-prod-neu` + 3 аппа (`ca-tracker-artur-{api,web,bot}`),
  PostgreSQL 16 `psql-tracker-artur-prod` (db `sales_tracker`), Log Analytics
  `law-tracker-artur-prod-neu`, 14 alert-правил, managed cert.
- DNS `tracker` (CNAME) + `asuid.tracker` (TXT) в зоне `adarasoft.com` (`dns-rg`).
- Cron-страж PG на mh-central (`tracker-pg-keep-stopped.sh` + строка crontab).
- KV namespace `tracker-artur--*` (11 секретов) → soft-delete (recoverable до ~2026-09-13).

## Бэкапы
- **Дамп БД:** `~/backups/tracker_artur-final-2026-06-15.sql.gz` на mh-central
  (schema + 14 таблиц; БД была пересоздана пустой 2026-05-31, данных минимум).
- **Конфиг аппов:** `ca-tracker-artur-*.json` в этой папке (секреты отредачены `az`).
- **Имена секретов:** `secret-names.txt` (per-app secretRef), `kv-secret-names.txt` (KV namespace).

## Что сохранено
- GitHub-репо `bronxtc52/tracker_artur` (код = история, не удалён).
- KV-секреты в soft-delete 90 дней (страховка).
