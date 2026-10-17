#!/bin/sh
# Called by qBittorrent hooks and the log watcher. Never evaluate torrent metadata.
set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo 'qbittorrent-gotify: usage: notify.sh EVENT NAME [CATEGORY]' >&2
  exit 1
fi

reason=''
case "$1" in
  finished)
    title='qBittorrent: download finished'
    priority=5
    ;;
  added)
    title='qBittorrent: torrent added'
    priority=0
    ;;
  ratio-limit|seeding-time-limit|inactive-seeding-time-limit)
    title='qBittorrent: seeding stopped'
    priority=5
    case "$1" in
      ratio-limit) reason='share ratio limit reached' ;;
      seeding-time-limit) reason='seeding time limit reached' ;;
      inactive-seeding-time-limit) reason='inactive seeding time limit reached' ;;
    esac
    ;;
  *)
    echo 'qbittorrent-gotify: unsupported event' >&2
    exit 1
    ;;
esac

token_file=${GOTIFY_TOKEN_FILE:-/var/run/secrets/gotify/token}
if [ ! -r "$token_file" ]; then
  echo 'qbittorrent-gotify: token file is unavailable' >&2
  exit 1
fi
token=$(cat "$token_file")
# Gotify tokens can contain dots. Reject curl configuration injection.
case "$token" in
  ''|*[!a-zA-Z0-9_.-]*)
    echo 'qbittorrent-gotify: invalid token file' >&2
    exit 1
    ;;
esac

message=$2
if [ -n "$reason" ]; then
  message=$(printf '%s\nReason: %s' "$message" "$reason")
fi
if [ -n "${3:-}" ]; then
  message=$(printf '%s\nCategory: %s' "$message" "$3")
fi
endpoint=${GOTIFY_URL:-https://gotify.igou.io}

for attempt in 1 2 3; do
  # Read the authorization header from stdin so the token is absent from argv.
  # Discard response bodies and curl errors; neither belongs in diagnostic logs.
  if status=$(printf 'header = "X-Gotify-Key: %s"\n' "$token" | curl \
    --config - \
    --silent \
    --proto '=https' \
    --connect-timeout 5 \
    --max-time 8 \
    --output /dev/null \
    --write-out '%{http_code}' \
    --data-urlencode "title=$title" \
    --data-urlencode "message=$message" \
    --data-urlencode "priority=$priority" \
    --url "${endpoint%/}/message" 2>/dev/null); then
    result=0
  else
    result=$?
  fi

  if [ "$result" -eq 0 ]; then
    case "$status" in
      2??) exit 0 ;;
      408|429|5??) ;; # Retry temporary HTTP failures only.
      *) break ;;
    esac
  else
    case "$result" in
      6|7|28|35|52|55|56) ;; # DNS, connection, timeout or interrupted transfer.
      *) break ;;
    esac
  fi

  if [ "$attempt" -lt 3 ]; then
    sleep "$attempt"
  fi
done

printf 'qbittorrent-gotify: delivery failed (attempts=%s, curl=%s, HTTP=%s)\n' \
  "$attempt" "$result" "$status" >&2
exit 1
