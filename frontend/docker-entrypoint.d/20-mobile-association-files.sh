#!/bin/sh

set -eu

if [ -n "${APPLE_TEAM_ID:-}" ]; then
  mkdir -p /usr/share/nginx/html/.well-known
  printf '%s' '{"applinks":{"details":[{"appIDs":["'"${APPLE_TEAM_ID}"'.mn.oyuns.workspace"],"components":[{"/":"/mobile-auth/telegram/callback"}]}]}}' \
    > /usr/share/nginx/html/.well-known/apple-app-site-association
fi

if [ -n "${ANDROID_SIGNING_CERT_SHA256:-}" ]; then
  fingerprints="$(printf '%s' "$ANDROID_SIGNING_CERT_SHA256" | awk -F, '{ for (i = 1; i <= NF; i++) { if (i > 1) printf ","; printf "\"%s\"", $i } }')"
  mkdir -p /usr/share/nginx/html/.well-known
  printf '%s' '[{"relation":["delegate_permission/common.handle_all_urls"],"target":{"namespace":"android_app","package_name":"mn.oyuns.workspace","sha256_cert_fingerprints":['"${fingerprints}"']}}]' \
    > /usr/share/nginx/html/.well-known/assetlinks.json
fi
