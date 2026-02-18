#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IMAGE_NAME="bonnieplusplus"
TAG="latest"

usage() {
  echo "Usage: $0 <registry>" >&2
  echo "" >&2
  echo "Builds the bonnie++ container image and pushes it to the specified registry." >&2
  echo "" >&2
  echo "Examples:" >&2
  echo "  $0 quay.io/myuser" >&2
  echo "  $0 registry.example.com/benchmarks" >&2
  exit 1
}

if [ $# -ne 1 ]; then
  usage
fi

REGISTRY="$1"
FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"

echo "Building ${FULL_IMAGE}..."
podman build -t "${FULL_IMAGE}" "${SCRIPT_DIR}"

echo "Pushing ${FULL_IMAGE}..."
podman push "${FULL_IMAGE}"

echo "Done. Update bonnieplusplus.yml containerImage to: ${FULL_IMAGE}"
