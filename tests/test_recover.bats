#!/usr/bin/env bats
# test_recover.bats — BATS tests for output/recover.sh
#
# All external binaries are mocked via MOCK_BIN_DIR (prepended to PATH inside
# recover.sh via the ${MOCK_BIN_DIR:+${MOCK_BIN_DIR}:} prefix).

load "helpers/common"

RECOVER_SH=""

setup() {
    setup_test_env

    # Locate recover.sh relative to this test file
    RECOVER_SH="$(cd "$(dirname "${BATS_TEST_FILENAME}")/.." && pwd)/output/recover.sh"

    # Create a minimal install dir so docker compose doesn't complain about missing path
    mkdir -p "${MOCK_BIN_DIR}/../install" 2>/dev/null || true

    # Default mock binaries (succeed silently unless overridden per-test)
    _write_mock curl    "exit 0"
    _write_mock pgrep   "exit 1"          # import NOT running by default
    _write_mock python3 "exit 0"
    _write_mock nohup   "exit 0"
    _write_mock sudo    "exit 0"
    _write_mock stat    'echo 0'
    _write_mock date    'echo 9999999999'
    _write_mock docker  "exit 0"
    _write_mock crontab 'echo ""'
    _write_mock tee     'cat'
    _write_mock sleep   'exit 0'
    _write_mock kill    'exit 0'
    _write_mock head    'echo ""'
    _write_mock mount   "echo '//nas/share on ${TEST_NAS_DIR} (nfs)'"

    # Default env
    export IMMICH_URL="http://localhost:2283"
    export NAS_MOUNT_POINT="${TEST_NAS_DIR}"
    export IMMICH_API_KEY="test-api-key"
}

teardown() {
    teardown_test_env
    rm -f /tmp/immich_recover.lock
    rm -f "${RECOVER_SH%/*}/import.pid"
}

# ---------------------------------------------------------------------------
# Helper: write a mock binary to MOCK_BIN_DIR
# ---------------------------------------------------------------------------
_write_mock() {
    local name="$1"
    local body="$2"
    cat > "${MOCK_BIN_DIR}/${name}" <<MOCK
#!/usr/bin/env bash
${body}
MOCK
    chmod +x "${MOCK_BIN_DIR}/${name}"
}

# ---------------------------------------------------------------------------
# Helper: run recover.sh --once with all required env overrides
# ---------------------------------------------------------------------------
_run_recover() {
    local args=("$@")
    run env \
        MOCK_BIN_DIR="${MOCK_BIN_DIR}" \
        IMMICH_URL="${IMMICH_URL}" \
        NAS_MOUNT_POINT="${NAS_MOUNT_POINT}" \
        IMMICH_API_KEY="${IMMICH_API_KEY:-}" \
        bash "${RECOVER_SH}" --once "${args[@]}" 2>&1
}

# ---------------------------------------------------------------------------
# Helper: write a live PID to the import PID file
# ---------------------------------------------------------------------------
_write_import_pid() {
    echo "$$" > "${RECOVER_SH%/*}/import.pid"
}

# ===========================================================================
# Test 1 — --once: healthy NAS and Immich → no recovery triggered
# ===========================================================================
@test "--once skips recovery when NAS mounted and Immich healthy" {
    _write_mock curl "exit 0"

    _run_recover
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"All healthy"* ]]
}

# ===========================================================================
# Test 2 — --once: does not start import (import is the loop's responsibility)
# ===========================================================================
@test "--once does not start import even when infrastructure is healthy" {
    _write_mock curl "exit 0"
    # python3 should NOT be called by --once
    _write_mock python3 "echo 'python3 CALLED'; exit 0"

    _run_recover
    [ "${status}" -eq 0 ]
    [[ "${output}" != *"python3 CALLED"* ]]
    [[ "${output}" != *"Starting import"* ]]
}

# ===========================================================================
# Test 3 — --once: full recovery when Immich is unhealthy
# ===========================================================================
@test "--once triggers full recovery when Immich is unhealthy" {
    _write_mock curl "exit 1"

    _run_recover
    [[ "${output}" == *"FULL RECOVERY"* ]]
}

# ===========================================================================
# Test 4 — --once: full recovery when NAS is not mounted
# ===========================================================================
@test "--once triggers full recovery when NAS is not mounted" {
    _write_mock mount "exit 0"
    _write_mock curl "exit 0"

    _run_recover
    [[ "${output}" == *"FULL RECOVERY"* ]]
}

# ===========================================================================
# Test 5 — --once: full recovery fails when mount.sh is not found
# ===========================================================================
@test "--once full recovery fails when mount.sh is not found" {
    _write_mock mount "exit 0"
    _write_mock curl "exit 0"

    local mount_sh="${RECOVER_SH%/*}/mount.sh"
    local backup="${mount_sh}.bak_$$"
    mv "${mount_sh}" "${backup}"

    _run_recover
    local rc="${status}"

    mv "${backup}" "${mount_sh}"

    [ "${rc}" -ne 0 ]
    [[ "${output}" == *"cannot remount NAS"* ]]
}

# ===========================================================================
# Test 6 — skips if another recovery instance is already running (live PID)
# ===========================================================================
@test "skips if another recovery instance is already running (live PID in lock file)" {
    echo "$$" > /tmp/immich_recover.lock

    _run_recover
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"Already running"* ]]

    rm -f /tmp/immich_recover.lock
}

# ===========================================================================
# Test 7 — removes stale lock and proceeds when PID in lock is dead
# ===========================================================================
@test "removes stale lock file and proceeds when PID in lock is dead" {
    echo "99999" > /tmp/immich_recover.lock

    # Make kill mock always fail (simulates dead PID)
    _write_mock kill "exit 1"
    _write_mock curl "exit 0"

    _run_recover
    [[ "${output}" == *"Stale lock"* ]]
}

# ===========================================================================
# Test 8 — --once exits after a single check cycle (no loop startup message)
# ===========================================================================
@test "--once flag exits after a single check cycle" {
    _write_mock curl "exit 0"

    _run_recover
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"All healthy"* ]]
    [[ "${output}" != *"Recovery monitor started"* ]]
}

# ===========================================================================
# Test 9 — --setup writes sudoers entry for diskutil and mount.sh
# ===========================================================================
@test "--setup writes sudoers entry for diskutil and mount.sh" {
    run env MOCK_BIN_DIR="${MOCK_BIN_DIR}" bash "${RECOVER_SH}" --setup
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"sudoers"* ]]
}

# ===========================================================================
# Test 10 — --setup warns when .env.local does not exist
# ===========================================================================
@test "--setup warns when .env.local does not exist" {
    rm -f "${RECOVER_SH%/*}/.env.local"

    run env MOCK_BIN_DIR="${MOCK_BIN_DIR}" bash "${RECOVER_SH}" --setup
    [ "${status}" -eq 0 ]
    [[ "${output}" == *".env.local not found"* ]]
}

# ===========================================================================
# Test 11 — loop logs startup message and runs import in foreground
# ===========================================================================
@test "loop logs startup message and runs import in foreground" {
    _write_mock curl "exit 0"

    run env \
        MOCK_BIN_DIR="${MOCK_BIN_DIR}" \
        IMMICH_URL="${IMMICH_URL}" \
        NAS_MOUNT_POINT="${NAS_MOUNT_POINT}" \
        IMMICH_API_KEY="${IMMICH_API_KEY:-}" \
        RECOVER_MAX_ITERATIONS=1 \
        bash "${RECOVER_SH}" 2>&1
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"Recovery monitor started"* ]]
    [[ "${output}" == *"Starting import"* ]]
}

# ===========================================================================
# Test 12 — loop starts import after full recovery
# ===========================================================================
@test "loop starts import in foreground after full recovery" {
    # NAS not mounted → full recovery first, then loop starts import
    _write_mock mount "exit 0"
    _write_mock curl "exit 0"

    run env \
        MOCK_BIN_DIR="${MOCK_BIN_DIR}" \
        IMMICH_URL="${IMMICH_URL}" \
        NAS_MOUNT_POINT="${NAS_MOUNT_POINT}" \
        IMMICH_API_KEY="${IMMICH_API_KEY:-}" \
        RECOVER_MAX_ITERATIONS=1 \
        bash "${RECOVER_SH}" 2>&1
    [[ "${output}" == *"FULL RECOVERY"* ]]
    [[ "${output}" == *"Starting import"* ]]
}

# ===========================================================================
# Test 13 — loop: "Import finished" logged after import exits
# ===========================================================================
@test "loop logs Import finished after import process exits" {
    _write_mock curl "exit 0"

    run env \
        MOCK_BIN_DIR="${MOCK_BIN_DIR}" \
        IMMICH_URL="${IMMICH_URL}" \
        NAS_MOUNT_POINT="${NAS_MOUNT_POINT}" \
        IMMICH_API_KEY="${IMMICH_API_KEY:-}" \
        RECOVER_MAX_ITERATIONS=1 \
        bash "${RECOVER_SH}" 2>&1
    [[ "${output}" == *"Import finished"* ]]
}

# ===========================================================================
# Test 14 — loop: IMMICH_API_KEY not set → error logged when starting import
# ===========================================================================
@test "loop logs IMMICH_API_KEY error when API key is not set" {
    _write_mock curl "exit 0"

    run env \
        MOCK_BIN_DIR="${MOCK_BIN_DIR}" \
        IMMICH_URL="${IMMICH_URL}" \
        NAS_MOUNT_POINT="${NAS_MOUNT_POINT}" \
        IMMICH_API_KEY="" \
        RECOVER_MAX_ITERATIONS=1 \
        bash "${RECOVER_SH}" 2>&1
    [[ "${output}" == *"IMMICH_API_KEY not set"* ]]
}

# ===========================================================================
# Test 15 — stop_import uses PID file when available
# ===========================================================================
@test "stop_import uses PID file to stop import during full recovery" {
    # Start a throwaway background process and write its PID.
    # Use absolute path to avoid the mock sleep (which exits immediately).
    # Using $$ would kill the test itself since kill is a bash builtin.
    /bin/sleep 9999 &
    local fake_pid=$!
    echo "${fake_pid}" > "${RECOVER_SH%/*}/import.pid"
    # NAS not mounted → full recovery → stop_import called
    _write_mock mount "exit 0"
    _write_mock curl "exit 0"

    _run_recover
    kill "${fake_pid}" 2>/dev/null || true   # clean up if still alive

    [[ "${output}" == *"FULL RECOVERY"* ]]
    # stop_import should have found the PID and logged stopping it
    [[ "${output}" == *"Stopping import process"* ]]
}

# ===========================================================================
# Test 16 — stop_import falls back to pgrep when PID file has dead PID
# ===========================================================================
@test "stop_import uses pgrep fallback when PID file has dead PID" {
    # Dead PID in import.pid
    echo "99999" > "${RECOVER_SH%/*}/import.pid"
    # kill -0 fails (dead PID), pgrep fallback returns a PID
    _write_mock kill "exit 1"
    _write_mock pgrep "echo 12345; exit 0"
    # NAS not mounted → full recovery → stop_import called
    _write_mock mount "exit 0"
    _write_mock curl "exit 0"

    _run_recover
    [[ "${output}" == *"FULL RECOVERY"* ]]
    # stop_import should have fallen back to pgrep and found the process
    [[ "${output}" == *"Stopping import process"* ]]
}

# ===========================================================================
# Test 17 — loop: IMMICH_WITH_VIDEO=true passes --withvideo to python3
# ===========================================================================
@test "loop passes --withvideo to python3 when IMMICH_WITH_VIDEO=true" {
    _write_mock curl "exit 0"
    _write_mock python3 "echo \"python3 args: \$*\"; exit 0"

    run env \
        MOCK_BIN_DIR="${MOCK_BIN_DIR}" \
        IMMICH_URL="${IMMICH_URL}" \
        NAS_MOUNT_POINT="${NAS_MOUNT_POINT}" \
        IMMICH_API_KEY="test-key" \
        IMMICH_WITH_VIDEO="true" \
        RECOVER_MAX_ITERATIONS=1 \
        bash "${RECOVER_SH}" 2>&1
    [[ "${output}" == *"video mode"* ]]
    [[ "${output}" == *"--withvideo"* ]]
}

# ===========================================================================
# Test 18 — loop: multiple iterations check infrastructure between import runs
# ===========================================================================
@test "loop re-checks infrastructure after each import run" {
    _write_mock curl "exit 0"

    run env \
        MOCK_BIN_DIR="${MOCK_BIN_DIR}" \
        IMMICH_URL="${IMMICH_URL}" \
        NAS_MOUNT_POINT="${NAS_MOUNT_POINT}" \
        IMMICH_API_KEY="${IMMICH_API_KEY:-}" \
        RECOVER_MAX_ITERATIONS=2 \
        bash "${RECOVER_SH}" 2>&1
    [ "${status}" -eq 0 ]
    # Health check should appear twice
    [[ "${output}" == *"Health check"* ]]
    [[ "${output}" == *"Import finished"* ]]
}

# ===========================================================================
# Test 19 — --once: full recovery when NAS mounted but NFS not responding
# ===========================================================================
@test "--once triggers full recovery when NAS mounted but NFS not responding" {
    # Default mount mock outputs the NAS line → nas_is_mounted() passes.
    # NAS_PROBE_CMD=/usr/bin/false fails immediately → nas_is_responding() returns 1.
    # Result: _nas=no → full recovery triggered.
    _write_mock curl "exit 0"

    run env \
        MOCK_BIN_DIR="${MOCK_BIN_DIR}" \
        IMMICH_URL="${IMMICH_URL}" \
        NAS_MOUNT_POINT="${NAS_MOUNT_POINT}" \
        IMMICH_API_KEY="${IMMICH_API_KEY:-}" \
        NAS_PROBE_CMD="/usr/bin/false" \
        NAS_PROBE_TIMEOUT="1" \
        bash "${RECOVER_SH}" --once 2>&1
    [[ "${output}" == *"FULL RECOVERY"* ]]
}

# ===========================================================================
# Test 20 — loop: watchdog starts and stops cleanly, normal operation unaffected
# ===========================================================================
@test "loop completes normally with NAS watchdog enabled" {
    _write_mock curl "exit 0"

    run env \
        MOCK_BIN_DIR="${MOCK_BIN_DIR}" \
        IMMICH_URL="${IMMICH_URL}" \
        NAS_MOUNT_POINT="${NAS_MOUNT_POINT}" \
        IMMICH_API_KEY="${IMMICH_API_KEY:-}" \
        NAS_PROBE_CMD="/bin/ls" \
        NAS_WATCHDOG_INTERVAL="9999" \
        RECOVER_MAX_ITERATIONS=1 \
        bash "${RECOVER_SH}" 2>&1
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"Import finished"* ]]
}

# ===========================================================================
# Test 21 — watchdog force-unmounts NAS (via diskutil) when NFS not responding
# ===========================================================================
@test "watchdog force-unmounts NAS when NFS not responding during import" {
    _write_mock curl "exit 0"

    # Stateful probe: succeeds on first call (run_check passes), fails on second (watchdog fires)
    local probe_state="${MOCK_BIN_DIR}/probe_state"
    echo "first" > "${probe_state}"
    cat > "${MOCK_BIN_DIR}/probe.sh" <<PROBE_SCRIPT
#!/usr/bin/env bash
state=\$(cat "${probe_state}" 2>/dev/null || echo fail)
if [[ "\$state" == first ]]; then
    echo later > "${probe_state}"
    exit 0
fi
exit 1
PROBE_SCRIPT
    chmod +x "${MOCK_BIN_DIR}/probe.sh"

    # Capture sudo arguments to verify diskutil was invoked
    local sudo_log="${MOCK_BIN_DIR}/sudo_calls.log"
    cat > "${MOCK_BIN_DIR}/sudo" <<SUDO_SCRIPT
#!/usr/bin/env bash
echo "\$*" >> "${sudo_log}"
exit 0
SUDO_SCRIPT
    chmod +x "${MOCK_BIN_DIR}/sudo"

    # Mock python3: write real PID to import.pid then sleep so watchdog can kill it
    local import_pid_file="${RECOVER_SH%/*}/import.pid"
    cat > "${MOCK_BIN_DIR}/python3" <<PY_SCRIPT
#!/usr/bin/env bash
echo \$\$ > "${import_pid_file}"
/bin/sleep 10
exit 0
PY_SCRIPT
    chmod +x "${MOCK_BIN_DIR}/python3"

    run env \
        MOCK_BIN_DIR="${MOCK_BIN_DIR}" \
        IMMICH_URL="${IMMICH_URL}" \
        NAS_MOUNT_POINT="${NAS_MOUNT_POINT}" \
        IMMICH_API_KEY="test-key" \
        NAS_PROBE_CMD="${MOCK_BIN_DIR}/probe.sh" \
        NAS_PROBE_TIMEOUT="1" \
        NAS_WATCHDOG_INTERVAL="1" \
        RECOVER_MAX_ITERATIONS=1 \
        bash "${RECOVER_SH}" 2>&1

    [[ "${output}" == *"NAS watchdog"* ]]
    [[ "$(cat "${sudo_log}" 2>/dev/null)" == *"diskutil"* ]]
}

# ===========================================================================
# Test 22 — full recovery aborts when NAS not responding after remount
# ===========================================================================
@test "full recovery aborts when NAS not responding after remount" {
    # NAS not mounted → triggers full recovery
    _write_mock mount "exit 0"
    _write_mock curl "exit 0"

    # Post-remount NAS probe always fails (NFS still flaky after remount)
    run env \
        MOCK_BIN_DIR="${MOCK_BIN_DIR}" \
        IMMICH_URL="${IMMICH_URL}" \
        NAS_MOUNT_POINT="${NAS_MOUNT_POINT}" \
        IMMICH_API_KEY="${IMMICH_API_KEY:-}" \
        NAS_PROBE_CMD="/usr/bin/false" \
        NAS_PROBE_TIMEOUT="1" \
        bash "${RECOVER_SH}" --once 2>&1

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"NAS not responding after remount"* ]]
}

# ===========================================================================
# Test 23 — docker compose down timeout: logs warning and continues recovery
# ===========================================================================
@test "full recovery continues when docker compose down times out" {
    # NAS not mounted → triggers full recovery
    _write_mock mount "exit 0"
    _write_mock curl "exit 0"

    # docker compose down hangs; everything else exits 0
    cat > "${MOCK_BIN_DIR}/docker" <<'DOCKERMOCK'
#!/usr/bin/env bash
[[ "$1" == "compose" ]] || exit 0
shift
[[ "$1" == "--project-directory" ]] || exit 0
shift 2
[[ "$1" == "down" ]] && { /bin/sleep 30; exit 0; }
exit 0
DOCKERMOCK
    chmod +x "${MOCK_BIN_DIR}/docker"

    run env \
        MOCK_BIN_DIR="${MOCK_BIN_DIR}" \
        IMMICH_URL="${IMMICH_URL}" \
        NAS_MOUNT_POINT="${NAS_MOUNT_POINT}" \
        IMMICH_API_KEY="${IMMICH_API_KEY:-}" \
        DOCKER_DOWN_TIMEOUT="2" \
        bash "${RECOVER_SH}" --once 2>&1

    [[ "${output}" == *"docker compose timed out"* ]]
    [[ "${output}" == *"continuing recovery anyway"* ]]
    # Recovery should have continued past the down timeout
    [[ "${output}" == *"Remounting NAS"* ]]
}

# ===========================================================================
# Test 24 — docker compose up timeout: aborts recovery, loop will retry
# ===========================================================================
@test "full recovery aborts when docker compose up times out" {
    # NAS not mounted → triggers full recovery
    _write_mock mount "exit 0"
    _write_mock curl "exit 0"

    # docker compose up hangs; everything else exits 0
    cat > "${MOCK_BIN_DIR}/docker" <<'DOCKERMOCK'
#!/usr/bin/env bash
[[ "$1" == "compose" ]] || exit 0
shift
[[ "$1" == "--project-directory" ]] || exit 0
shift 2
[[ "$1" == "up" ]] && { /bin/sleep 30; exit 0; }
exit 0
DOCKERMOCK
    chmod +x "${MOCK_BIN_DIR}/docker"

    run env \
        MOCK_BIN_DIR="${MOCK_BIN_DIR}" \
        IMMICH_URL="${IMMICH_URL}" \
        NAS_MOUNT_POINT="${NAS_MOUNT_POINT}" \
        IMMICH_API_KEY="${IMMICH_API_KEY:-}" \
        DOCKER_UP_TIMEOUT="2" \
        bash "${RECOVER_SH}" --once 2>&1

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"docker compose up timed out"* ]]
}
