#!/bin/sh
set -e

if ! alembic upgrade head; then
  if [ "${ALLOW_START_WITH_MIGRATION_FAILURE:-false}" != "true" ]; then
    echo "Database migration failed; refusing to start. Set ALLOW_START_WITH_MIGRATION_FAILURE=true only for recovery." >&2
    exit 1
  fi

  echo "WARNING: database migration failed; starting API in recovery mode." >&2
  echo "Run 'alembic upgrade head' from the backend container terminal, then redeploy." >&2
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
