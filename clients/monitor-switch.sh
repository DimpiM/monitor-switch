#!/usr/bin/env bash
#
# Switch the monitor's input from a hotkey, a script, or a terminal.
#
#   monitor-switch.sh dp1        switch to a specific input
#   monitor-switch.sh toggle     cycle through the configured inputs
#   monitor-switch.sh state      print the current input
#
# Point it somewhere else with:
#   export MONITOR_SWITCH_HOST=192.0.2.10:8765
#
set -uo pipefail

HOST="${MONITOR_SWITCH_HOST:-monitor-switch.local:8765}"

# A verified switch takes ~2 s, and a request arriving mid-poll waits for the
# in-flight bus transaction. Ten seconds is comfortably above both while still
# failing rather than hanging if the Pi is off.
TIMEOUT="${MONITOR_SWITCH_TIMEOUT:-10}"

usage() {
  cat >&2 <<EOF
usage: ${0##*/} <input-id|toggle|state>

  input-id   an option id from the monitor profile, e.g. dp1, dp2, hdmi
  toggle     cycle through the inputs configured as toggle_between
  state      print the input currently on screen

Environment:
  MONITOR_SWITCH_HOST     host:port of the service (default monitor-switch.local:8765)
  MONITOR_SWITCH_TIMEOUT  seconds to wait (default 10)
EOF
  exit 2
}

# Hotkeys have no terminal to print to, so failures go to the desktop instead.
# Falls back to stderr where no notification daemon exists.
notify() {
  local message="$1"
  if command -v notify-send >/dev/null 2>&1; then
    notify-send --app-name="monitor-switch" --urgency=critical \
      "Monitor switch failed" "$message" 2>/dev/null || true
  fi
  echo "monitor-switch: $message" >&2
}

request() {
  local method="$1" path="$2"
  curl -sS -X "$method" --max-time "$TIMEOUT" \
    -w '\n%{http_code}' "http://${HOST}${path}" 2>&1
}

main() {
  [ $# -eq 1 ] || usage
  local target="$1" response body status

  case "$target" in
    -h | --help) usage ;;
    state) response=$(request GET /api/input) ;;
    toggle) response=$(request POST /api/toggle) ;;
    *) response=$(request POST "/api/input/${target}") ;;
  esac

  status="${response##*$'\n'}"
  body="${response%$'\n'*}"

  if [ "$status" != "200" ]; then
    # The service answers errors as JSON with a human-readable "message".
    local detail
    detail=$(printf '%s' "$body" | sed -n 's/.*"message": *"\([^"]*\)".*/\1/p')
    notify "${detail:-${body:-no response from ${HOST}}}"
    return 1
  fi

  printf '%s\n' "$body" | sed -n 's/.*"display": *"\([^"]*\)".*/\1/p'
}

main "$@"
