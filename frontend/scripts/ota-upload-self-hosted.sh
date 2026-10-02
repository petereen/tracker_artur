#!/usr/bin/env bash

set -euo pipefail

: "${OTA_BUNDLE_VERSION:?Set OTA_BUNDLE_VERSION, for example 1.0.1}"
: "${OTA_UPLOAD_TOKEN:?Set OTA_UPLOAD_TOKEN in your local shell or CI secret store}"

OTA_API_URL="${OTA_API_URL:-https://erp.oyuns.mn/api/v1/mobile-updates}"
OTA_CHANNEL="${OTA_CHANNEL:-staging}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

if ! command -v zip >/dev/null 2>&1; then
  echo 'The OTA upload script requires the zip utility.' >&2
  exit 1
fi

cd "$FRONTEND_DIR"
npm run test
npm run build

ARCHIVE="${TEMP_DIR}/oyuns-${OTA_BUNDLE_VERSION}.zip"
(cd dist && zip -qr "$ARCHIVE" .)

# The lowest native binary build this web bundle runs on. The bundle
# feature-detects native plugins, so raise it only when it cannot run at all
# on an older binary; the server then withholds it from those binaries.
OTA_MIN_NATIVE_VERSION="${OTA_MIN_NATIVE_VERSION:-$(node -p "require('./native-requirements.json').min_native_version")}"
if ! [[ "$OTA_MIN_NATIVE_VERSION" =~ ^[1-9][0-9]*$ ]]; then
  echo "min_native_version must be a positive integer (got '${OTA_MIN_NATIVE_VERSION}')." >&2
  exit 1
fi

curl --fail-with-body --silent --show-error \
  -X POST \
  -H "Authorization: Bearer ${OTA_UPLOAD_TOKEN}" \
  -F "version=${OTA_BUNDLE_VERSION}" \
  -F "min_native_version=${OTA_MIN_NATIVE_VERSION}" \
  -F "file=@${ARCHIVE};type=application/zip" \
  "${OTA_API_URL%/}/bundles"
printf '\nUploaded %s. Promote it with OTA_BUNDLE_VERSION=%s npm run ota:promote:production\n' "$OTA_BUNDLE_VERSION" "$OTA_BUNDLE_VERSION"
