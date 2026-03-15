#!/usr/bin/env bash
# stop.sh - Stops all Immich containers (data is preserved).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${IMMICH_INSTALL_DIR:-${SCRIPT_DIR}/install}"
DOCKER_CMD="${DOCKER_CMD:-docker}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { echo "[INFO]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------
command -v "${DOCKER_CMD}" >/dev/null 2>&1 \
    || error "Docker is not installed. Install it from https://www.docker.com/products/docker-desktop/"

"${DOCKER_CMD}" info >/dev/null 2>&1 \
    || error "Docker daemon is not running. Please start Docker Desktop and try again."

[[ -f "${INSTALL_DIR}/docker-compose.yml" ]] \
    || error "Immich is not installed yet. Run install.sh first."

# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------
info "Stopping Immich..."
"${DOCKER_CMD}" compose --project-directory "${INSTALL_DIR}" down
info "Immich stopped. Your data is preserved."
