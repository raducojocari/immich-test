#!/usr/bin/env bash
# reset.sh - Wipes all Immich data so the system can be started fresh.
#            Config files (.env, compose files) are preserved.
#
# Usage:
#   ./output/reset.sh           # prompts for confirmation
#   ./output/reset.sh --confirm # skips prompt (for scripted use)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${IMMICH_INSTALL_DIR:-${SCRIPT_DIR}/install}"
IMMICH_NAS_MOUNT="${IMMICH_NAS_MOUNT:-/Volumes/nas}"
IMMICH_STORAGE_DIR="${IMMICH_STORAGE_DIR:-${IMMICH_NAS_MOUNT}/immich}"
LOG_FILE="${IMMICH_IMPORT_LOG:-${SCRIPT_DIR}/import.log}"
DOCKER_CMD="${DOCKER_CMD:-docker}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { echo "[INFO]  $*"; }
ok()    { echo "[OK]    $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Parse flags
# ---------------------------------------------------------------------------
CONFIRM=0
for arg in "$@"; do
    case "${arg}" in
        --confirm) CONFIRM=1 ;;
        *) error "Unknown argument: ${arg}" ;;
    esac
done

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
# Confirmation prompt
# ---------------------------------------------------------------------------
if [[ "${CONFIRM}" -eq 0 ]]; then
    echo ""
    echo "WARNING: This will permanently delete the following:"
    echo "  1. Immich uploaded photos:  ${IMMICH_STORAGE_DIR}"
    echo "  2. Postgres database:       ${INSTALL_DIR}/postgres"
    echo "  3. Import checkpoint log:   ${LOG_FILE}"
    echo ""
    echo "Config files (.env, compose files) will be preserved."
    echo "The NAS Google Photos source directory will NOT be touched."
    echo ""
    printf 'Type "yes" to continue: '
    read -r answer || answer=""
    if [[ "${answer}" != "yes" ]]; then
        info "Aborted."
        exit 0
    fi
fi

# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------
info "Stopping Immich containers..."
"${DOCKER_CMD}" compose --project-directory "${INSTALL_DIR}" down
ok "Containers stopped."

if [[ -d "${IMMICH_STORAGE_DIR}" ]]; then
    info "Deleting Immich storage: ${IMMICH_STORAGE_DIR}"
    rm -rf "${IMMICH_STORAGE_DIR}"
    ok "Deleted."
else
    info "Immich storage directory not found, skipping: ${IMMICH_STORAGE_DIR}"
fi

if [[ -d "${INSTALL_DIR}/postgres" ]]; then
    info "Deleting Postgres data: ${INSTALL_DIR}/postgres"
    rm -rf "${INSTALL_DIR}/postgres"
    ok "Deleted."
else
    info "Postgres data directory not found, skipping: ${INSTALL_DIR}/postgres"
fi

if [[ -f "${LOG_FILE}" ]]; then
    info "Clearing import log: ${LOG_FILE}"
    > "${LOG_FILE}"
    ok "Cleared."
else
    info "Import log not found, skipping: ${LOG_FILE}"
fi

echo ""
info "Reset complete. Run ./output/start.sh to bring up a fresh empty instance."
