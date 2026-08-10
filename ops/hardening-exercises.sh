#!/usr/bin/env bash
set -euo pipefail

compose=(docker compose -f docker-compose.yml -f docker-compose.hardening.yml)
exercise=${1:-validate}
artifact_dir=${HARDENING_ARTIFACT_DIR:-/private/tmp/tracker-artur-hardening}
mkdir -p "$artifact_dir"

case "$exercise" in
  validate)
    "${compose[@]}" config --quiet
    "${compose[@]}" up -d db clamav backend backend-replica worker frontend
    "${compose[@]}" exec -T backend alembic heads
    "${compose[@]}" exec -T -e RUN_POSTGRES_TESTS=1 backend python -m pytest -q tests/test_enterprise_foundation.py tests/test_enterprise_integrations.py tests/test_remaining_enterprise_phases.py
    ;;
  migration)
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    dump="$artifact_dir/pre-migration-$stamp.dump"
    "${compose[@]}" exec -T db pg_dump -U tracker -d sales_tracker -Fc > "$dump"
    test -s "$dump"
    "${compose[@]}" exec -T backend alembic upgrade head
    ;;
  backup-restore)
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    verify_db="tracker_restore_verify_${stamp//[^0-9]/}"
    dump="$artifact_dir/restore-verify-$stamp.dump"
    "${compose[@]}" exec -T db pg_dump -U tracker -d sales_tracker -Fc > "$dump"
    "${compose[@]}" exec -T db createdb -U tracker "$verify_db"
    trap '"${compose[@]}" exec -T db dropdb -U tracker --if-exists "$verify_db"' EXIT
    "${compose[@]}" exec -T db pg_restore -U tracker -d "$verify_db" --exit-on-error < "$dump"
    "${compose[@]}" exec -T db psql -U tracker -d "$verify_db" -v ON_ERROR_STOP=1 -c 'SELECT count(*) FROM alembic_version;'
    ;;
  load)
    requests=${HARDENING_REQUESTS:-500}
    seq "$requests" | xargs -P 20 -I{} curl --fail --silent --show-error http://127.0.0.1:8010/health >/dev/null
    ;;
  notification-burst)
    "${compose[@]}" exec -T db psql -U tracker -d sales_tracker -v ON_ERROR_STOP=1 -c "BEGIN; INSERT INTO job_queue(job_type,payload,state,run_at,dedup_key) SELECT 'healthcheck','{}','pending',now(),'hardening-burst-'||g FROM generate_series(1,1000) g; SELECT count(*) FROM job_queue WHERE dedup_key LIKE 'hardening-burst-%'; ROLLBACK;"
    ;;
  worker-recovery)
    "${compose[@]}" stop worker
    "${compose[@]}" exec -T db psql -U tracker -d sales_tracker -v ON_ERROR_STOP=1 -c "INSERT INTO job_queue(job_type,payload,state,run_at,dedup_key) VALUES ('healthcheck','{}','pending',now(),'hardening-recovery-'||extract(epoch from now())) ON CONFLICT DO NOTHING;"
    "${compose[@]}" start worker
    "${compose[@]}" logs --since=2m worker
    ;;
  *)
    echo "usage: $0 {validate|migration|backup-restore|load|notification-burst|worker-recovery}" >&2
    exit 2
    ;;
esac
