#!/usr/bin/env bash
# Snapshot the current set of serial devices, then watch for the first change
# (any device appearing or disappearing). Useful for identifying which
# /dev/cu.* path corresponds to a cable you're about to plug in.
#
# Usage:
#   scripts/watch-serial-devices.sh [output-file]
#
# Environment:
#   INTERVAL   poll interval in seconds (default 1)

set -euo pipefail

OUT="${1:-serial-devices.txt}"
INTERVAL="${INTERVAL:-1}"

# List all /dev/cu.* devices that look like real adapters (skip built-ins).
list_devices() {
  ls /dev/cu.* 2>/dev/null \
    | grep -vE 'cu\.(Bluetooth|debug-console)$' \
    | sort
}

baseline=$(list_devices)
echo "=== baseline ($(date '+%H:%M:%S')) ==="
if [[ -z "$baseline" ]]; then
  echo "(no serial devices currently attached)"
else
  echo "$baseline"
fi
echo
echo "Watching for changes (poll every ${INTERVAL}s, Ctrl-C to abort)..."

while true; do
  sleep "$INTERVAL"
  current=$(list_devices)
  if [[ "$current" != "$baseline" ]]; then
    added=$(comm -13 <(echo "$baseline") <(echo "$current"))
    removed=$(comm -23 <(echo "$baseline") <(echo "$current"))
    echo
    echo "=== change detected ($(date '+%H:%M:%S')) ==="
    [[ -n "$added"   ]] && echo "+ added:"   && echo "$added"   | sed 's/^/    /'
    [[ -n "$removed" ]] && echo "- removed:" && echo "$removed" | sed 's/^/    /'
    {
      echo "# captured: $(date)"
      echo "# baseline:"
      echo "$baseline" | sed 's/^/#   /'
      echo "# added:"
      [[ -n "$added"   ]] && echo "$added"   | sed 's/^/#   + /' || echo "#   (none)"
      echo "# removed:"
      [[ -n "$removed" ]] && echo "$removed" | sed 's/^/#   - /' || echo "#   (none)"
      echo
      echo "# current state:"
      echo "$current"
    } > "$OUT"
    echo
    echo "wrote -> $OUT"
    exit 0
  fi
done
