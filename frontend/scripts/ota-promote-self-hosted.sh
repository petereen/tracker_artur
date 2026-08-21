#!/usr/bin/env bash

set -euo pipefail

: "${OTA_BUNDLE_VERSION:?Set OTA_BUNDLE_VERSION to an already uploaded version}"
: "${OTA_UPLOAD_TOKEN:?Set OTA_UPLOAD_TOKEN in your local shell or CI secret store}"

OTA_API_URL="${OTA_API_URL:-https://erp.oyuns.mn/api/v1/mobile-updates}"
OTA_CHANNEL="${OTA_CHANNEL:-production}"

curl --fail-with-body --silent --show-error \
  -X PUT \
  -H "Authorization: Bearer ${OTA_UPLOAD_TOKEN}" \
  "${OTA_API_URL%/}/channels/${OTA_CHANNEL}/bundle/${OTA_BUNDLE_VERSION}"
printf '\nPromoted %s to %s.\n' "$OTA_BUNDLE_VERSION" "$OTA_CHANNEL"
