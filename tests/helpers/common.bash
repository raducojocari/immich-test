#!/usr/bin/env bash
# common.bash - Shared setup/teardown helpers for all Immich script tests.
#
# Usage in test files:
#   load "helpers/common"
#   setup()    { setup_test_env; }
#   teardown() { teardown_test_env; }

# ---------------------------------------------------------------------------
# setup_test_env
# Creates isolated temp directories, a mock docker binary, and overrides all
# script configuration variables so tests never touch the real NAS or Docker.
# ---------------------------------------------------------------------------
setup_test_env() {
    # --- Temp directories ---
    export MOCK_BIN_DIR
    MOCK_BIN_DIR="$(mktemp -d)"

    export TEST_NAS_DIR
    TEST_NAS_DIR="$(mktemp -d)"

    export TEST_INSTALL_PARENT
    TEST_INSTALL_PARENT="$(mktemp -d)"

    # Prepend mock bin dir so our mock docker is found first
    export PATH="${MOCK_BIN_DIR}:${PATH}"

    # --- NAS directory structure ---
    mkdir -p "${TEST_NAS_DIR}/Google Photos/Radu"

    export TEST_STORAGE_DIR
    TEST_STORAGE_DIR="$(mktemp -d)"

    # --- Script overrides ---
    export IMMICH_NAS_MOUNT="${TEST_NAS_DIR}"
    export IMMICH_INSTALL_DIR="${TEST_INSTALL_PARENT}/install"
    export IMMICH_STORAGE_DIR="${TEST_STORAGE_DIR}"
    export IMMICH_IMPORT_LOG="${TEST_INSTALL_PARENT}/import.log"

    # Point downloads at local fixture files so tests run offline
    export IMMICH_DOCKER_COMPOSE_URL="file://${BATS_TEST_DIRNAME}/fixtures/docker-compose.yml"
    export IMMICH_EXAMPLE_ENV_URL="file://${BATS_TEST_DIRNAME}/fixtures/example.env"

    # Use the mock docker binary
    _create_docker_mock
    export DOCKER_CMD="${MOCK_BIN_DIR}/docker"

    # Use the real system curl (file:// URLs work natively)
    export CURL_CMD="curl"
}

# ---------------------------------------------------------------------------
# teardown_test_env
# Cleans up all temp directories created by setup_test_env.
# ---------------------------------------------------------------------------
teardown_test_env() {
    rm -rf "${MOCK_BIN_DIR:-}" "${TEST_NAS_DIR:-}" "${TEST_INSTALL_PARENT:-}" "${TEST_STORAGE_DIR:-}"
}

# ---------------------------------------------------------------------------
# _create_docker_mock
# Writes a mock docker executable to MOCK_BIN_DIR.
#
# Failure injection (set before running the script under test):
#   MOCK_DOCKER_COMPOSE_VERSION_FAILS=1  -> docker compose version exits 1
#   MOCK_DOCKER_INFO_FAILS=1             -> docker info exits 1
#   MOCK_DOCKER_COMPOSE_UP_FAILS=1       -> docker compose ... up exits 1
#   MOCK_DOCKER_COMPOSE_DOWN_FAILS=1     -> docker compose ... down exits 1
# ---------------------------------------------------------------------------
_create_docker_mock() {
    cat > "${MOCK_BIN_DIR}/docker" <<'MOCK'
#!/usr/bin/env bash
case "${1}" in
  info)
    [[ "${MOCK_DOCKER_INFO_FAILS:-0}" == "1" ]] && exit 1
    echo "Server: Docker Engine"
    ;;
  compose)
    shift
    case "${1}" in
      version)
        [[ "${MOCK_DOCKER_COMPOSE_VERSION_FAILS:-0}" == "1" ]] && exit 1
        echo "Docker Compose version v2.20.0"
        ;;
      --project-directory)
        # docker compose --project-directory <dir> <command> [options]
        # After shift: $1=--project-directory  $2=<dir>  $3=<command>
        case "${3}" in
          up)   [[ "${MOCK_DOCKER_COMPOSE_UP_FAILS:-0}"   == "1" ]] && exit 1 ;;
          down) [[ "${MOCK_DOCKER_COMPOSE_DOWN_FAILS:-0}" == "1" ]] && exit 1 ;;
        esac
        ;;
    esac
    ;;
esac
exit 0
MOCK
    chmod +x "${MOCK_BIN_DIR}/docker"
}

# ---------------------------------------------------------------------------
# run_script <path> [args...]
# Runs a script capturing both stdout and stderr into $output.
# Use with the BATS `run` command:
#   run run_script "${MY_SCRIPT}"
# ---------------------------------------------------------------------------
run_script() {
    bash -c '"$@" 2>&1' _ "$@"
}
