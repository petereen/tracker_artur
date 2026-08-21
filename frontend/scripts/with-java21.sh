#!/usr/bin/env bash

set -euo pipefail

java_major_version() {
  local version
  version="$("$1" -version 2>&1 | sed -n 's/.*version "\([^."]*\).*/\1/p' | head -1)"
  printf '%s' "${version:-0}"
}

is_supported_java() {
  local major
  major="$(java_major_version "$1")"
  [[ "$major" =~ ^[0-9]+$ ]] && (( major >= 21 && major <= 24 ))
}

if [[ -n "${JAVA_HOME:-}" && -x "${JAVA_HOME}/bin/java" ]] && is_supported_java "${JAVA_HOME}/bin/java"; then
  :
elif [[ -x "/usr/libexec/java_home" ]] && java_home_21="$(/usr/libexec/java_home -v 21 2>/dev/null || true)" && [[ -x "${java_home_21}/bin/java" ]]; then
  export JAVA_HOME="$java_home_21"
elif [[ -x "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home/bin/java" ]]; then
  export JAVA_HOME="/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
elif [[ -x "/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home/bin/java" ]]; then
  export JAVA_HOME="/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
elif command -v java >/dev/null 2>&1 && is_supported_java "$(command -v java)"; then
  export JAVA_HOME="$(dirname "$(dirname "$(command -v java)")")"
else
  echo "Android builds require JDK 21 (Gradle 8.14.3 does not support Java 26). Set JAVA_HOME to a JDK 21 installation." >&2
  exit 1
fi

export PATH="$JAVA_HOME/bin:$PATH"
exec "$@"
