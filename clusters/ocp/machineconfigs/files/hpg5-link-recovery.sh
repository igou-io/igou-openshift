#!/bin/bash
# AMT can leave the HP I219-LM at 10 Mb/s after blocking PHY setup at boot.
set -uo pipefail

device_matches() {
  [[ $(cat /sys/class/net/eno1/address 2>/dev/null) == f8:b4:6a:ab:55:c7 ]]
}

boot_seconds() {
  local uptime
  read -r uptime _ < /proc/uptime || return 1
  printf '%s\n' "${uptime%%.*}"
}

already_attempted() {
  [[ -e /run/hpg5-link-recovery.attempted ]]
}

mark_attempted() {
  (set -o noclobber; : > /run/hpg5-link-recovery.attempted)
}

link_speed() {
  local carrier speed
  carrier=$(cat /sys/class/net/eno1/carrier 2>/dev/null) || return 1
  speed=$(cat /sys/class/net/eno1/speed 2>/dev/null) || return 1
  [[ $carrier == 1 && $speed =~ ^[0-9]+$ && $speed -gt 0 ]] || return 1
  printf '%s\n' "$speed"
}

renegotiate() {
  timeout 15 ethtool -r eno1
}

main() {
  local uptime speed attempt
  device_matches || { echo 'Skipping: HP eno1 MAC does not match.'; return 0; }
  uptime=$(boot_seconds) || return 1
  [[ $uptime =~ ^[0-9]+$ ]] || return 1
  # Installing or restarting the timer on a running worker must not reset it.
  (( uptime <= 600 )) || { echo 'Skipping: boot recovery window has ended.'; return 0; }
  already_attempted && { echo 'Skipping: recovery was already attempted this boot.'; return 0; }
  speed=$(link_speed) || { echo 'Link down or speed unknown; leaving eno1 alone.' >&2; return 1; }
  (( speed >= 1000 )) && { echo "eno1 is healthy at ${speed} Mb/s."; return 0; }
  mark_attempted || { echo 'Cannot reserve the recovery attempt.' >&2; return 1; }
  for attempt in 1 2; do
    echo "eno1 is at ${speed} Mb/s; renegotiation attempt ${attempt}/2."
    renegotiate || echo 'Renegotiation command failed; checking the link.' >&2
    sleep 10
    speed=$(link_speed) || { echo 'Link down or speed unknown after reset; stopping.' >&2; return 1; }
    (( speed >= 1000 )) && { echo "eno1 recovered to ${speed} Mb/s."; return 0; }
  done
  echo "eno1 remains at ${speed} Mb/s; no further resets this boot. Check AMT redirection and the link." >&2
  return 1
}

if [[ ${BASH_SOURCE[0]:-$0} == "$0" ]]; then
  main
fi
