#!/usr/bin/env bats
# test_start.bats - Tests for output/start.sh

load "helpers/common"

START_SH="${BATS_TEST_DIRNAME}/../output/start.sh"

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
    run run_script "${START_SH}"
    [ "$status" -ne 0 ]
    [[ "$output" =~ "Docker is not installed" ]]
}

@test "fails when docker daemon is not running" {
    export MOCK_DOCKER_INFO_FAILS=1
    run run_script "${START_SH}"
    [ "$status" -ne 0 ]
    [[ "$output" =~ "Docker daemon is not running" ]]
}

@test "fails when immich is not installed" {
    rm -f "${TEST_INSTALL_PARENT}/install/docker-compose.yml"
    run run_script "${START_SH}"
    [ "$status" -ne 0 ]
    [[ "$output" =~ "Immich is not installed yet" ]]
}

# ---------------------------------------------------------------------------
# Normal operation
# ---------------------------------------------------------------------------

@test "starts containers successfully" {
    run run_script "${START_SH}"
    [ "$status" -eq 0 ]
}

@test "outputs immich URL after starting" {
    run run_script "${START_SH}"
    [ "$status" -eq 0 ]
    [[ "$output" =~ "http://localhost:2283" ]]
}

@test "fails when docker compose up fails" {
    export MOCK_DOCKER_COMPOSE_UP_FAILS=1
    run run_script "${START_SH}"
    [ "$status" -ne 0 ]
}
