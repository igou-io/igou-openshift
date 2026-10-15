#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$HOME" /data/rust /data/steamcmd
# SteamCMD updates its own directory. Copy it off the immutable image so
# OpenShift's assigned UID can write without root or an anyuid SCC.
if [[ ! -x /data/steamcmd/steamcmd.sh ]]; then
  cp -R /home/steam/steamcmd/. /data/steamcmd/
fi
/data/steamcmd/steamcmd.sh +force_install_dir /data/rust \
  +login anonymous +app_update 258550 validate +quit
mkdir -p "$HOME/.steam/sdk64" /data/rust/server/homelab/cfg
ln -sfn /data/steamcmd/linux64/steamclient.so "$HOME/.steam/sdk64/steamclient.so"
