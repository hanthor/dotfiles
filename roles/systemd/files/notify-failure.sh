#!/usr/bin/env bash
# notify-failure UNIT — post "<host>: <unit> failed" to ntfy.
#
# Run by notify-failure@.service, which units reach through
# OnFailure=notify-failure@%n.service. NTFY_TOPIC / NTFY_SERVER come from
# ~/.config/notify-failure.env (written by the systemd role from the
# Bitwarden item `ntfy-topic`). With no topic it only logs, and it always
# exits 0: a broken notifier must never become a second failed unit.
#
# The body is deliberately short (host, unit, result) — ntfy topics are
# guessable, so no journal excerpts are posted. Read them with
# `journalctl --user -u UNIT`.
set -u

unit=${1:-unknown.service}
host=$(hostname 2>/dev/null || uname -n)
result=$(systemctl --user show -p Result --value "$unit" 2>/dev/null || true)
msg="${host}: ${unit} failed${result:+ (result: ${result})}. journalctl --user -u ${unit}"

echo "notify-failure: ${msg}" >&2

if [ -z "${NTFY_TOPIC:-}" ]; then
  echo "notify-failure: NTFY_TOPIC not set (no ~/.config/notify-failure.env); journal only" >&2
  exit 0
fi

server=${NTFY_SERVER:-https://ntfy.sh}
if ! curl -fsS --max-time 15 \
    -H "Title: ${host}: ${unit} failed" \
    -H "Tags: warning" \
    -d "$msg" "${server%/}/${NTFY_TOPIC}" >/dev/null; then
  echo "notify-failure: posting to ntfy failed" >&2
fi
exit 0
