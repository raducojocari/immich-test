#!/usr/bin/env bats
# test_reset.bats - Tests for output/reset.sh

load "helpers/common"

RESET_SH="${BATS_TEST_DIRNAME}/../output/reset.sh"

setup() {
    setup_test_env
    # Create a fake docker-compose.yml so the "not installed" check passes by default
    mkdir -p "${TEST_INSTALL_PARENT}/install"
    touch "${TEST_INSTALL_PARENT}/install/docker-compose.yml"
}

teardown() { teardown_test_env; }

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

@test "fails when docker is not in PATH" {
    export DOCKER_CMD="nonexistent_docker_command_xyz"
    run run_script "${RESET_SH}" --confirm
    [ "$status" -ne 0 ]
    [[ "$output" =~ "Docker is not installed" ]]
}

@test "fails when docker daemon is not running" {
    export MOCK_DOCKER_INFO_FAILS=1
    run run_script "${RESET_SH}" --confirm
    [ "$status" -ne 0 ]
    [[ "$output" =~ "Docker daemon is not running" ]]
}

@test "fails when immich is not installed" {
    rm -f "${TEST_INSTALL_PARENT}/install/docker-compose.yml"
    run run_script "${RESET_SH}" --confirm
    [ "$status" -ne 0 ]
    [[ "$output" =~ "Immich is not installed yet" ]]
}

# ---------------------------------------------------------------------------
# Confirmation prompt
# ---------------------------------------------------------------------------

@test "aborts without --confirm when prompt receives empty input" {
    run bash -c "printf '' | bash '${RESET_SH}' 2>&1"
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Aborted" ]]
}

@test "aborts without --confirm when prompt receives non-yes input" {
    run bash -c "echo 'no' | bash '${RESET_SH}' 2>&1"
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Aborted" ]]
}

@test "--confirm flag skips prompt entirely" {
    run run_script "${RESET_SH}" --confirm
    [ "$status" -eq 0 ]
    ! [[ "$output" =~ 'Type "yes"' ]]
}

# ---------------------------------------------------------------------------
# Normal operation
# ---------------------------------------------------------------------------

@test "stops containers before deleting data" {
    run run_script "${RESET_SH}" --confirm
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Stopping Immich containers" ]]
}

@test "deletes immich storage directory" {
    mkdir -p "${IMMICH_STORAGE_DIR}/photos"
    run run_script "${RESET_SH}" --confirm
    [ "$status" -eq 0 ]
    [ ! -d "${IMMICH_STORAGE_DIR}" ]
}

@test "deletes postgres data directory" {
    mkdir -p "${TEST_INSTALL_PARENT}/install/postgres/data"
    run run_script "${RESET_SH}" --confirm
    [ "$status" -eq 0 ]
    [ ! -d "${TEST_INSTALL_PARENT}/install/postgres" ]
}

@test "clears import log" {
    echo "CREATED /some/file.jpg" > "${IMMICH_IMPORT_LOG}"
    run run_script "${RESET_SH}" --confirm
    [ "$status" -eq 0 ]
    [ -f "${IMMICH_IMPORT_LOG}" ]
    [ ! -s "${IMMICH_IMPORT_LOG}" ]
}

@test "is idempotent when data directories do not exist" {
    run run_script "${RESET_SH}" --confirm
    [ "$status" -eq 0 ]
    run run_script "${RESET_SH}" --confirm
    [ "$status" -eq 0 ]
}

@test "fails when docker compose down fails" {
    export MOCK_DOCKER_COMPOSE_DOWN_FAILS=1
    run run_script "${RESET_SH}" --confirm
    [ "$status" -ne 0 ]
}
