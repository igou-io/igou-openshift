#!/usr/bin/env bash
# Reliably boot a Windows installer VM into Setup.
#
# autoboot.py can only catch the "Press any key to boot from CD" prompt if it is
# already pressing when the ~5s window appears. On a cold VMI the VNC proxy
# isn't ready that early, so a single run often lands on the UEFI Front Page and
# misses it. This wrapper force power-cycles the VM and retries autoboot.py from
# a known start each time, until it detects the blue Windows Setup screen.
#
# This step is inherent to Windows install media on any headless UEFI VM (the
# media requires a keypress to boot); it is NOT related to any storage backend.
#
# Usage: boot-vm.sh <vm-name> <local-vnc-port> [namespace]
set -u
NAME=${1:?vm name required}
PORT=${2:?local vnc port required}
NS=${3:-windows-images}
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for attempt in 1 2 3 4 5 6; do
  echo "[$NAME] attempt $attempt: power-cycle"
  virtctl stop "$NAME" -n "$NS" --force --grace-period=0 >/dev/null 2>&1
  for i in $(seq 1 15); do
    [ -z "$(oc get vmi "$NAME" -n "$NS" -o jsonpath='{.status.phase}' 2>/dev/null)" ] && break
    sleep 3
  done
  virtctl start "$NAME" -n "$NS" >/dev/null 2>&1
  for i in $(seq 1 25); do
    [ "$(oc get vmi "$NAME" -n "$NS" -o jsonpath='{.status.phase}' 2>/dev/null)" = Running ] && break
    sleep 3
  done
  # start the VNC proxy; autoboot.py self-retries the connection until it is up
  virtctl vnc "$NAME" -n "$NS" --proxy-only --port "$PORT" >/dev/null 2>&1 &
  vpid=$!
  sleep 3
  python3 "$DIR/autoboot.py" "$PORT" 160
  rc=$?
  kill "$vpid" >/dev/null 2>&1
  echo "[$NAME] attempt $attempt autoboot rc=$rc"
  [ "$rc" = 0 ] && { echo "[$NAME] in Setup"; exit 0; }
done
echo "[$NAME] FAILED to reach Setup after retries"; exit 1
