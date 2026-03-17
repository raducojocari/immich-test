#!/usr/bin/env bash
# install.sh - Downloads and configures Immich for local deployment.
# Stores uploaded photos on the NAS and mounts an external Google Photos library.

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# All variables can be overridden via environment variables for testing.
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${IMMICH_INSTALL_DIR:-${SCRIPT_DIR}/install}"

NAS_MOUNT="${IMMICH_NAS_MOUNT:-/Volumes/nas}"
IMMICH_STORAGE="${NAS_MOUNT}/immich"
EXTERNAL_PHOTOS="${NAS_MOUNT}/Google Photos/Radu"

DOCKER_COMPOSE_URL="${IMMICH_DOCKER_COMPOSE_URL:-https://github.com/immich-app/immich/releases/latest/download/docker-compose.yml}"
EXAMPLE_ENV_URL="${IMMICH_EXAMPLE_ENV_URL:-https://github.com/immich-app/immich/releases/latest/download/example.env}"

DOCKER_CMD="${DOCKER_CMD:-docker}"
CURL_CMD="${CURL_CMD:-curl}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { echo "[INFO]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------
check_prerequisites() {
    info "Checking prerequisites..."

    command -v "${DOCKER_CMD}" >/dev/null 2>&1 \
        || error "Docker is not installed. Install it from https://www.docker.com/products/docker-desktop/"

    "${DOCKER_CMD}" compose version >/dev/null 2>&1 \
        || error "Docker Compose plugin is not available. Make sure Docker Desktop is up to date."

    "${DOCKER_CMD}" info >/dev/null 2>&1 \
        || error "Docker daemon is not running. Please start Docker Desktop and try again."

    command -v "${CURL_CMD}" >/dev/null 2>&1 \
        || error "curl is not installed. Install it with: brew install curl"

    info "All prerequisites satisfied."
}

check_nas_mounted() {
    info "Checking NAS mount at ${NAS_MOUNT}..."

    [[ -d "${NAS_MOUNT}" ]] \
        || error "NAS is not mounted at ${NAS_MOUNT}. Mount the Unifi NAS volume and try again."

    [[ -d "${EXTERNAL_PHOTOS}" ]] \
        || error "Google Photos directory not found at '${EXTERNAL_PHOTOS}'. Verify the NAS is mounted and the path is correct."

    info "NAS mount verified."
}

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
create_directories() {
    info "Creating Immich storage directory at ${IMMICH_STORAGE}..."
    mkdir -p "${IMMICH_STORAGE}" \
        || error "Failed to create ${IMMICH_STORAGE}. Check NAS permissions."
    info "Storage directory ready."
}

download_immich_config() {
    info "Downloading Immich docker-compose.yml..."
    "${CURL_CMD}" --fail --silent --show-error --location \
        "${DOCKER_COMPOSE_URL}" \
        --output "${INSTALL_DIR}/docker-compose.yml" \
        || error "Failed to download docker-compose.yml from ${DOCKER_COMPOSE_URL}"

    info "Downloading Immich example.env..."
    "${CURL_CMD}" --fail --silent --show-error --location \
        "${EXAMPLE_ENV_URL}" \
        --output "${INSTALL_DIR}/example.env" \
        || error "Failed to download example.env from ${EXAMPLE_ENV_URL}"

    info "Immich configuration files downloaded."
}

configure_env() {
    local env_file="${INSTALL_DIR}/.env"

    info "Configuring .env..."

    cp "${INSTALL_DIR}/example.env" "${env_file}"

    # Point upload storage to NAS
    sed -i '' "s|UPLOAD_LOCATION=.*|UPLOAD_LOCATION=${IMMICH_STORAGE}|" "${env_file}"

    # Keep postgres data local (inside the install dir) for reliability
    sed -i '' "s|DB_DATA_LOCATION=.*|DB_DATA_LOCATION=${INSTALL_DIR}/postgres|" "${env_file}"

    info ".env configured."
}

create_compose_override() {
    info "Creating docker-compose.override.yml for external library mount..."

    # The override mounts the Google Photos folder into the immich-server container
    # as a read-only external library. After starting Immich, add the path
    # /usr/src/app/external/google-photos as an External Library in the web UI.
    cat > "${INSTALL_DIR}/docker-compose.override.yml" <<EOF
# docker-compose.override.yml
# Adds a read-only mount so Immich can scan the Google Photos library from the NAS.
# In the Immich web UI, add "/usr/src/app/external/google-photos" as an External Library.
services:
  immich-server:
    volumes:
      - "${EXTERNAL_PHOTOS}:/usr/src/app/external/google-photos:ro"
EOF

    info "docker-compose.override.yml created."
}

setup_sudoers() {
    local mount_script="${SCRIPT_DIR}/mount.sh"
    local sudoers_file="/etc/sudoers.d/immich-mount"
    local current_user
    current_user="$(whoami)"

    info "Configuring passwordless sudo for mount.sh..."
    echo "${current_user} ALL=(root) NOPASSWD: ${mount_script}" \
        | sudo tee "${sudoers_file}" > /dev/null
    sudo chmod 440 "${sudoers_file}"
    info "Passwordless sudo configured: ${sudoers_file}"
}

start_immich() {
    info "Starting Immich containers..."
    "${DOCKER_CMD}" compose --project-directory "${INSTALL_DIR}" up --detach \
        || error "Failed to start Immich containers. Check the Docker logs for details."
    info "Immich is running. Open http://localhost:2283 to complete setup."
    info ""
    info "Next step: In the Immich web UI go to Administration > Libraries,"
    info "create an External Library, and set the path to:"
    info "  /usr/src/app/external/google-photos"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    info "=== Immich Installer ==="

    check_prerequisites
    check_nas_mounted
    create_directories

    mkdir -p "${INSTALL_DIR}"
    download_immich_config
    configure_env
    create_compose_override
    setup_sudoers
    start_immich

    info "=== Installation complete ==="
}

main "$@"
