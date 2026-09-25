#!/bin/sh
set -eu
# Omnigent is baked into devenv. Only the selected lab harness needs setup.
# renovate: datasource=npm depName=@earendil-works/pi-coding-agent
PI_VERSION=0.84.2
npm install --global --prefix /sandbox/.local --no-audit --no-fund \
    "@earendil-works/pi-coding-agent@${PI_VERSION}"
omnigent --version
/sandbox/.local/bin/pi --version
