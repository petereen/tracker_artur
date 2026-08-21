#!/usr/bin/env bash

set -euo pipefail

: "${OTA_UPLOAD_TOKEN:?Set OTA_UPLOAD_TOKEN in your local shell or CI secret store}"

OTA_API_URL="${OTA_API_URL:-https://erp.oyuns.mn/api/v1/mobile-updates}"
OTA_CHANNEL="${OTA_CHANNEL:-production}"

curl --fail-with-body --silent --show-error \
  -X POST \
  -H "Authorization: Bearer ${OTA_UPLOAD_TOKEN}" \
  "${OTA_API_URL%/}/channels/${OTA_CHANNEL}/rollback"
printf '\nRolled back %s to its previous bundle.\n' "$OTA_CHANNEL"
