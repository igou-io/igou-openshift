#!/bin/bash
# Exercise the recovery policy without touching a host NIC or sleeping.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
script="$root/clusters/ocp/machineconfigs/files/hpg5-link-recovery.sh"
manifest="$root/clusters/ocp/machineconfigs/99-kata-oc-hpg5-link-recovery-machineconfig.yaml"
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT

"${PYTHON:-python3}" -c '
import base64, sys, yaml
with open(sys.argv[1]) as stream:
    source = yaml.safe_load(stream)["spec"]["config"]["storage"]["files"][0]["contents"]["source"]
sys.stdout.buffer.write(base64.b64decode(source.removeprefix("data:;base64,")))
' "$manifest" > "$fixture/rendered.sh"
cmp "$script" "$fixture/rendered.sh"
bash -n "$script"

run_case() (
  name=$1 match=$2 fixture_uptime=$3 previous=$4 sequence=$5 expected_status=$6 expected_resets=$7 reset_status=${8:-0}
  # shellcheck source=../../clusters/ocp/machineconfigs/files/hpg5-link-recovery.sh
  source "$script"
  read -ra speeds <<< "$sequence"
  printf '%s\n' "${speeds[@]}" > "$fixture/speeds"
  : > "$fixture/resets"
  rm -f "$fixture/attempted"
  [[ $previous == false ]] || touch "$fixture/attempted"
  device_matches() { [[ $match == true ]]; }
  boot_seconds() { echo "$fixture_uptime"; }
  already_attempted() { [[ -e "$fixture/attempted" ]]; }
  mark_attempted() { touch "$fixture/attempted"; }
  link_speed() {
    local speed
    read -r speed < "$fixture/speeds" || return 1
    sed -i '1d' "$fixture/speeds"
    [[ $speed != unknown ]] || return 1
    echo "$speed"
  }
  renegotiate() { echo reset >> "$fixture/resets"; return "$reset_status"; }
  sleep() { :; }
  status=0
  main > "$fixture/output" 2>&1 || status=$?
  resets=$(wc -l < "$fixture/resets")
  if [[ $status != "$expected_status" || $resets != "$expected_resets" ]]; then
    cat "$fixture/output"
    echo "FAIL $name: status=$status resets=$resets" >&2
    exit 1
  fi
  echo "PASS $name"
)
run_case other-device false 90 false '10' 0 0
run_case late-install true 601 false '10' 0 0
run_case healthy true 90 false '1000' 0 0
run_case faster-link true 90 false '2500' 0 0
run_case unknown-link true 90 false 'unknown' 1 0
run_case already-tried true 90 true '10' 0 0
run_case recovers-first true 90 false '10 1000' 0 1
run_case recovers-second true 90 false '10 100 1000' 0 2
run_case firmware-blocked true 90 false '10 10 10' 1 2 1
run_case remains-slow true 90 false '100 100 100' 1 2
run_case loses-carrier true 90 false '10 unknown' 1 1
