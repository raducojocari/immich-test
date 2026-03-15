#!/usr/bin/env bats
# test_stop.bats - Tests for output/stop.sh

load "helpers/common"

STOP_SH="${BATS_TEST_DIRNAME}/../output/stop.sh"

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
    run run_script "${STOP_SH}"
    [ "$status" -ne 0 ]
    [[ "$output" =~ "Docker is not installed" ]]
}

@test "fails when docker daemon is not running" {
    export MOCK_DOCKER_INFO_FAILS=1
    run run_script "${STOP_SH}"
    [ "$status" -ne 0 ]
    [[ "$output" =~ "Docker daemon is not running" ]]
}

@test "fails when immich is not installed" {
    rm -f "${TEST_INSTALL_PARENT}/install/docker-compose.yml"
    run run_script "${STOP_SH}"
    [ "$status" -ne 0 ]
    [[ "$output" =~ "Immich is not installed yet" ]]
}

# ---------------------------------------------------------------------------
# Normal operation
# ---------------------------------------------------------------------------

@test "stops containers successfully" {
    run run_script "${STOP_SH}"
    [ "$status" -eq 0 ]
}

@test "outputs data preserved message after stopping" {
    run run_script "${STOP_SH}"
    [ "$status" -eq 0 ]
    [[ "$output" =~ "data is preserved" ]]
}

@test "fails when docker compose down fails" {
    export MOCK_DOCKER_COMPOSE_DOWN_FAILS=1
    run run_script "${STOP_SH}"
    [ "$status" -ne 0 ]
}
