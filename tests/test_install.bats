#!/usr/bin/env bats
# test_install.bats - Tests for output/install.sh

load "helpers/common"

INSTALL_SH="${BATS_TEST_DIRNAME}/../output/install.sh"

setup()    { setup_test_env; }
teardown() { teardown_test_env; }

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

@test "fails when docker is not in PATH" {
    export DOCKER_CMD="nonexistent_docker_command_xyz"
    run run_script "${INSTALL_SH}"
    [ "$status" -ne 0 ]
    [[ "$output" =~ "Docker is not installed" ]]
}

@test "fails when docker compose plugin is missing" {
    export MOCK_DOCKER_COMPOSE_VERSION_FAILS=1
    run run_script "${INSTALL_SH}"
    [ "$status" -ne 0 ]
    [[ "$output" =~ "Docker Compose plugin is not available" ]]
}

@test "fails when docker daemon is not running" {
    export MOCK_DOCKER_INFO_FAILS=1
    run run_script "${INSTALL_SH}"
    [ "$status" -ne 0 ]
    [[ "$output" =~ "Docker daemon is not running" ]]
}

@test "fails when curl is not in PATH" {
    export CURL_CMD="nonexistent_curl_command_xyz"
    run run_script "${INSTALL_SH}"
    [ "$status" -ne 0 ]
    [[ "$output" =~ "curl is not installed" ]]
}

# ---------------------------------------------------------------------------
# NAS checks
# ---------------------------------------------------------------------------

@test "fails when NAS is not mounted" {
    rm -rf "${TEST_NAS_DIR}"
    run run_script "${INSTALL_SH}"
    [ "$status" -ne 0 ]
    [[ "$output" =~ "NAS is not mounted" ]]
}

@test "fails when google photos directory does not exist" {
    rm -rf "${TEST_NAS_DIR}/Google Photos"
    run run_script "${INSTALL_SH}"
    [ "$status" -ne 0 ]
    [[ "$output" =~ "Google Photos directory not found" ]]
}

# ---------------------------------------------------------------------------
# Download failures
# ---------------------------------------------------------------------------

@test "fails when docker-compose.yml download fails" {
    export IMMICH_DOCKER_COMPOSE_URL="file:///nonexistent/path/docker-compose.yml"
    run run_script "${INSTALL_SH}"
    [ "$status" -ne 0 ]
    [[ "$output" =~ "Failed to download docker-compose.yml" ]]
}

@test "fails when example.env download fails" {
    export IMMICH_EXAMPLE_ENV_URL="file:///nonexistent/path/example.env"
    run run_script "${INSTALL_SH}"
    [ "$status" -ne 0 ]
    [[ "$output" =~ "Failed to download example.env" ]]
}

# ---------------------------------------------------------------------------
# Directory creation
# ---------------------------------------------------------------------------

@test "creates immich storage directory on NAS" {
    run run_script "${INSTALL_SH}"
    [ "$status" -eq 0 ]
    [ -d "${TEST_NAS_DIR}/immich" ]
}

# ---------------------------------------------------------------------------
# .env configuration
# ---------------------------------------------------------------------------

@test "sets UPLOAD_LOCATION to NAS immich directory in .env" {
    run run_script "${INSTALL_SH}"
    [ "$status" -eq 0 ]
    local env_file="${TEST_INSTALL_PARENT}/install/.env"
    [ -f "${env_file}" ]
    grep -q "UPLOAD_LOCATION=${TEST_NAS_DIR}/immich" "${env_file}"
}

@test "sets DB_DATA_LOCATION to install directory in .env" {
    run run_script "${INSTALL_SH}"
    [ "$status" -eq 0 ]
    local env_file="${TEST_INSTALL_PARENT}/install/.env"
    [ -f "${env_file}" ]
    grep -q "DB_DATA_LOCATION=${TEST_INSTALL_PARENT}/install/postgres" "${env_file}"
}

@test "preserves other .env variables unchanged" {
    run run_script "${INSTALL_SH}"
    [ "$status" -eq 0 ]
    local env_file="${TEST_INSTALL_PARENT}/install/.env"
    grep -q "^DB_PASSWORD=postgres" "${env_file}"
    grep -q "^DB_USERNAME=postgres" "${env_file}"
    grep -q "^DB_DATABASE_NAME=immich" "${env_file}"
}

# ---------------------------------------------------------------------------
# docker-compose.override.yml
# ---------------------------------------------------------------------------

@test "creates docker-compose.override.yml" {
    run run_script "${INSTALL_SH}"
    [ "$status" -eq 0 ]
    [ -f "${TEST_INSTALL_PARENT}/install/docker-compose.override.yml" ]
}

@test "override.yml targets the immich-server service" {
    run run_script "${INSTALL_SH}"
    [ "$status" -eq 0 ]
    grep -q "immich-server" "${TEST_INSTALL_PARENT}/install/docker-compose.override.yml"
}

@test "override.yml mounts google photos path into container" {
    run run_script "${INSTALL_SH}"
    [ "$status" -eq 0 ]
    grep -q "${TEST_NAS_DIR}/Google Photos/Radu" \
        "${TEST_INSTALL_PARENT}/install/docker-compose.override.yml"
}

@test "override.yml mounts google photos read-only" {
    run run_script "${INSTALL_SH}"
    [ "$status" -eq 0 ]
    grep -q ":ro" "${TEST_INSTALL_PARENT}/install/docker-compose.override.yml"
}

@test "override.yml mounts to the expected container path" {
    run run_script "${INSTALL_SH}"
    [ "$status" -eq 0 ]
    grep -q "/usr/src/app/external/google-photos" \
        "${TEST_INSTALL_PARENT}/install/docker-compose.override.yml"
}

# ---------------------------------------------------------------------------
# Container startup
# ---------------------------------------------------------------------------

@test "starts immich containers via docker compose up" {
    run run_script "${INSTALL_SH}"
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Immich is running" ]]
}

@test "fails when docker compose up fails" {
    export MOCK_DOCKER_COMPOSE_UP_FAILS=1
    run run_script "${INSTALL_SH}"
    [ "$status" -ne 0 ]
    [[ "$output" =~ "Failed to start Immich containers" ]]
}

@test "happy path succeeds end-to-end" {
    run run_script "${INSTALL_SH}"
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Installation complete" ]]
}
