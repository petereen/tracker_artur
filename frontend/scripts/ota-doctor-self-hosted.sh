#!/usr/bin/env bash

set -euo pipefail

OTA_API_URL="${OTA_API_URL:-https://erp.oyuns.mn/api/v1/mobile-updates}"
OTA_CHANNEL="${OTA_CHANNEL:-production}"

curl --fail-with-body --silent --show-error \
  -X POST \
  -H 'Content-Type: application/json' \
  -d "{\"app_id\":\"mn.oyuns.workspace\",\"channel\":\"${OTA_CHANNEL}\",\"platform\":\"android\",\"current_version\":\"builtin\"}" \
  "${OTA_API_URL%/}/check"
printf '\nSelf-hosted OTA endpoint is reachable.\n'
