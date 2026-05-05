#!/usr/bin/env bash
# Log into a Cisco IOS/IOS-XE device over serial and dump the running-config.
#
# Usage:
#   scripts/dump-cisco-config.sh [output-file]
#
# Environment:
#   SERIAL_DEV   serial device  (default: /dev/cu.usbserial-120)
#   BAUD         baud rate      (default: 9600)
#   IOS_USER     username       (prompted if unset)
#   IOS_PASS     login password (prompted if unset)
#   IOS_ENABLE   enable secret  (prompted if unset; send empty string if not needed)

set -euo pipefail

SERIAL_DEV="${SERIAL_DEV:-/dev/cu.usbserial-120}"
BAUD="${BAUD:-9600}"
OUT="${1:-router-config-$(date +%Y%m%d-%H%M%S).txt}"

if [[ ! -e "$SERIAL_DEV" ]]; then
  echo "error: $SERIAL_DEV does not exist" >&2
  exit 1
fi

# Force-clean any stale processes holding the port. Stale `expect` from a
# previous failed run is a common cause of mysterious TX failures: two
# processes racing for the same TTY drop characters.
holders=$(lsof -t "$SERIAL_DEV" 2>/dev/null || true)
if [[ -n "$holders" ]]; then
  echo "  -> port held by PIDs: $holders — killing"
  # shellcheck disable=SC2086
  kill -9 $holders 2>/dev/null || true
  sleep 1
  pkill -9 -f "expect.*dump-cisco-config" 2>/dev/null || true
  screen -wipe >/dev/null 2>&1 || true
fi
if lsof "$SERIAL_DEV" >/dev/null 2>&1; then
  echo "error: $SERIAL_DEV is still in use after cleanup" >&2
  lsof "$SERIAL_DEV" >&2
  exit 1
fi

# Strip any control characters the user's terminal may have smuggled in.
sanitize() { printf '%s' "$1" | LC_ALL=C tr -d '[:cntrl:]'; }

while [[ -z "${IOS_USER:-}" ]]; do
  read -rp "Username: " IOS_USER </dev/tty
  IOS_USER="$(sanitize "$IOS_USER")"
  [[ -z "$IOS_USER" ]] && echo "  (empty — try again)" >&2
done

if [[ -z "${IOS_PASS+x}" ]]; then
  read -rsp "Password: " IOS_PASS </dev/tty; echo
  IOS_PASS="$(sanitize "$IOS_PASS")"
fi
if [[ -z "${IOS_ENABLE+x}" ]]; then
  read -rsp "Enable secret (blank if none): " IOS_ENABLE </dev/tty; echo
  IOS_ENABLE="$(sanitize "$IOS_ENABLE")"
fi

echo "  -> user='$IOS_USER' (len=${#IOS_USER})  pass-len=${#IOS_PASS}  enable-len=${#IOS_ENABLE}"
echo "  -> dev='$SERIAL_DEV' baud=$BAUD -> $OUT"

export IOS_USER IOS_PASS IOS_ENABLE SERIAL_DEV BAUD OUT

exec python3 "$(dirname "$0")/dump-cisco-config.py"
