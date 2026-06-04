#!/usr/bin/env bash
# Alert-правила для tracker_artur (rg-tracker-artur-prod-neu) по образцу rg-mhg-lms-prod. БЕЗ action group.
# Стек: ca-tracker-artur-api (FastAPI) + ca-tracker-artur-bot (aiogram) = Python; ca-tracker-artur-web = nginx.
# Console-паттерны (Python) скоупим на api+bot — где живёт наш код; nginx-логи web не трогаем.
set -euo pipefail
SUB="c05debcb-f65a-4aee-9d1e-0f598536a024"
RG="rg-tracker-artur-prod-neu"
WS="/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.OperationalInsights/workspaces/law-tracker-artur-prod-neu"
APP_BASE="/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.App/containerapps"
TAGS="project=tracker-artur env=prod owner=bronxtc52"
APPS=(ca-tracker-artur-api ca-tracker-artur-web ca-tracker-artur-bot)

for APP in "${APPS[@]}"; do
  SCOPE="${APP_BASE}/${APP}"
  az monitor metrics alert create -n "al-${APP}-no-replicas" -g "$RG" --scopes "$SCOPE" \
    --condition "min Replicas < 1" --window-size 5m --evaluation-frequency 1m --severity 1 \
    --description "[$APP] нет активных реплик ≥5м" --tags $TAGS
  az monitor metrics alert create -n "al-${APP}-restarts" -g "$RG" --scopes "$SCOPE" \
    --condition "total RestartCount > 5" --window-size 15m --evaluation-frequency 5m --severity 2 \
    --description "[$APP] >5 рестартов за 15м" --tags $TAGS
  az monitor metrics alert create -n "al-${APP}-cpu-high" -g "$RG" --scopes "$SCOPE" \
    --condition "avg UsageNanoCores > 400000000" --window-size 10m --evaluation-frequency 5m --severity 3 \
    --description "[$APP] CPU > ~0.4 vCPU 10м (подгони порог)" --tags $TAGS
  az monitor metrics alert create -n "al-${APP}-memory-high" -g "$RG" --scopes "$SCOPE" \
    --condition "avg WorkingSetBytes > 419430400" --window-size 10m --evaluation-frequency 5m --severity 3 \
    --description "[$APP] RSS > ~400MiB 10м (подгони порог)" --tags $TAGS
done

az monitor scheduled-query create -n "al-tracker-artur-aca-system-failures" -g "$RG" \
  --scopes "$WS" --severity 1 --window-size 5m --evaluation-frequency 1m \
  --condition "count 'rows' > 0" \
  --condition-query rows="ContainerAppSystemLogs_CL | where TimeGenerated > ago(5m)
    | where ContainerAppName_s startswith 'ca-tracker-artur-'
    | where Reason_s in~ ('ProbeFailed','RevisionFailed','ContainerFailed','Failed')
       or Log_s has_any ('Probe failed','Revision failed','Container failed','failed startup probe')
    | summarize total=count(), hard=countif(Reason_s in~ ('RevisionFailed','ContainerFailed','Failed') or Log_s has_any ('Revision failed','Container failed'))
    | where hard > 0 or total >= 10" \
  --description "ACA system failures across tracker_artur apps" --tags $TAGS

az monitor scheduled-query create -n "al-tracker-artur-console-critical-errors" -g "$RG" \
  --scopes "$WS" --severity 2 --window-size 5m --evaluation-frequency 5m \
  --condition "count 'rows' > 0" \
  --condition-query rows="ContainerAppConsoleLogs_CL | where TimeGenerated > ago(5m)
    | where ContainerAppName_s in ('ca-tracker-artur-api','ca-tracker-artur-bot')
    | where Log_s has_any ('Traceback (most recent call','CRITICAL','OperationalError',
        'ECONNREFUSED','Connection refused','psycopg','asyncpg','MemoryError','TelegramRetryAfter')" \
  --description "Critical console errors (python/fastapi/aiogram/db) for tracker_artur api+bot" --tags $TAGS

echo "✅ tracker_artur alert-правила созданы (без уведомлений)."
