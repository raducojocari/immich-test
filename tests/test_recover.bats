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
    _write_mock stat    'echo 0'          # mtime = epoch; age will be very large
    _write_mock date    'echo 9999999999' # current time = far future
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

    # Create a non-empty checkpoint log (recent) so health check passes by default
    CHECKPOINT_LOG="${TEST_INSTALL_PARENT}/output/import.log"
    mkdir -p "$(dirname "${CHECKPOINT_LOG}")"
    echo "2026-03-18T10:00:00Z === Import started ===" > "${CHECKPOINT_LOG}"
}

teardown() {
    teardown_test_env
    rm -f /tmp/immich_recover.lock
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
# Helper: run recover.sh with all required env overrides
# ---------------------------------------------------------------------------
_run_recover() {
    local args=("$@")
    # Point CHECKPOINT_LOG and INSTALL_DIR at temp dirs
    SCRIPT_DIR_OVERRIDE="$(dirname "${RECOVER_SH}")"
    run env \
        MOCK_BIN_DIR="${MOCK_BIN_DIR}" \
        IMMICH_URL="${IMMICH_URL}" \
        NAS_MOUNT_POINT="${NAS_MOUNT_POINT}" \
        IMMICH_API_KEY="${IMMICH_API_KEY:-}" \
        bash "${RECOVER_SH}" "${args[@]}" 2>&1
}

# ---------------------------------------------------------------------------
# Override the checkpoint log path recover.sh uses by symlinking
# ---------------------------------------------------------------------------
_setup_recent_checkpoint() {
    # recover.sh uses ${SCRIPT_DIR}/import.log where SCRIPT_DIR=output/
    # We symlink output/import.log → our temp file
    local real_log="${RECOVER_SH%/*}/import.log"
    # Use a file that was just modified (age ≈ 0)
    echo "2026-03-18T10:00:00Z === Import started ===" > "${real_log}.test_$$"

    # Make stat return a very recent mtime and date return matching now
    local now
    now="$(date +%s 2>/dev/null || echo 9999)"
    _write_mock stat "echo ${now}"
    _write_mock date "echo ${now}"
    export _RECOVER_CHECKPOINT_OVERRIDE="${real_log}.test_$$"
}

_cleanup_checkpoint_override() {
    rm -f "${RECOVER_SH%/*}/import.log.test_$$"
}

# ===========================================================================
# Test 1 — skips when import running, Immich healthy, checkpoint recent
# ===========================================================================
@test "skips when import running, Immich healthy, checkpoint recent" {
    # import IS running
    _write_mock pgrep "exit 0"
    # Immich IS healthy (curl succeeds)
    _write_mock curl "exit 0"
    # Checkpoint is recent: stat returns now, date returns now
    local now=9999999999
    _write_mock stat "echo ${now}"
    _write_mock date "echo ${now}"

    # Ensure the real import.log exists and is non-empty
    echo "started" > "${RECOVER_SH%/*}/import.log"

    _run_recover
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"All healthy"* ]]
}

# ===========================================================================
# Test 2 — starts import only when import not running but Immich healthy
# ===========================================================================
@test "starts import only (no Docker restart) when import not running but Immich healthy" {
    # import NOT running (default pgrep exits 1)
    # Immich IS healthy
    _write_mock curl "exit 0"
    # Checkpoint is recent
    local now=9999999999
    _write_mock stat "echo ${now}"
    _write_mock date "echo ${now}"

    docker_called=0
    _write_mock docker "docker_called=1; exit 0"

    _run_recover
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"Import not running — starting import"* ]]
    # docker should NOT have been called for full recovery
    [[ "${output}" != *"FULL RECOVERY"* ]]
}

# ===========================================================================
# Test 3 — full recovery when Immich is unhealthy
# ===========================================================================
@test "performs full recovery when Immich is unhealthy" {
    # import IS running
    _write_mock pgrep "exit 0"
    # Immich NOT healthy
    _write_mock curl "exit 1"
    # Checkpoint is recent
    local now=9999999999
    _write_mock stat "echo ${now}"
    _write_mock date "echo ${now}"

    echo "started" > "${RECOVER_SH%/*}/import.log"

    _run_recover
    [[ "${output}" == *"FULL RECOVERY"* ]]
}

# ===========================================================================
# Test 4 — full recovery when checkpoint is stale (>720s)
# ===========================================================================
@test "performs full recovery when import running but checkpoint is stale" {
    # import IS running
    _write_mock pgrep "exit 0"
    # Immich IS healthy
    _write_mock curl "exit 0"
    # Checkpoint is stale: mtime=0, now=9999
    _write_mock stat "echo 0"
    _write_mock date "echo 9999"

    echo "started" > "${RECOVER_SH%/*}/import.log"

    _run_recover
    [[ "${output}" == *"FULL RECOVERY"* ]]
}

# ===========================================================================
# Test 5 — full recovery when import running and Immich is down
# ===========================================================================
@test "performs full recovery when import running and Immich is down" {
    _write_mock pgrep "exit 0"
    _write_mock curl "exit 1"
    local now=9999999999
    _write_mock stat "echo ${now}"
    _write_mock date "echo ${now}"

    echo "started" > "${RECOVER_SH%/*}/import.log"

    _run_recover
    [[ "${output}" == *"FULL RECOVERY"* ]]
}

# ===========================================================================
# Test 6 — skips if another recovery instance is already running (live PID)
# ===========================================================================
@test "skips if another recovery instance is already running (live PID in lock file)" {
    # Write our own PID into the lock file (we are alive)
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
    # Use a PID that cannot be alive (PID 1 on most systems is init, but
    # kill -0 on PID 99999 should fail on any normal system)
    echo "99999" > /tmp/immich_recover.lock

    # Make kill mock always fail (simulates dead PID)
    _write_mock kill "exit 1"

    # Healthy state so it just skips after removing lock
    _write_mock pgrep "exit 0"
    _write_mock curl "exit 0"
    local now=9999999999
    _write_mock stat "echo ${now}"
    _write_mock date "echo ${now}"
    echo "started" > "${RECOVER_SH%/*}/import.log"

    _run_recover
    # Lock should be gone (either removed or script ran through)
    [[ "${output}" == *"Stale lock"* ]]
}

# ===========================================================================
# Test 8 — --setup installs cron entry
# ===========================================================================
@test "--setup installs cron entry" {
    # crontab -l returns empty (no existing entry)
    _write_mock crontab 'case "${1}" in -l) echo "" ;; *) exit 0 ;; esac'

    run env MOCK_BIN_DIR="${MOCK_BIN_DIR}" bash "${RECOVER_SH}" --setup
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"Cron entry installed"* ]]
}

# ===========================================================================
# Test 9 — --setup writes sudoers entry for diskutil
# ===========================================================================
@test "--setup writes sudoers entry for diskutil" {
    # crontab already has our entry so only sudoers path is exercised
    _write_mock crontab 'case "${1}" in -l) echo "*/10 * * * * '"${RECOVER_SH}"'" ;; *) exit 0 ;; esac'

    run env MOCK_BIN_DIR="${MOCK_BIN_DIR}" bash "${RECOVER_SH}" --setup
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"sudoers"* ]]
}

# ===========================================================================
# Test 10 — --setup warns when .env.local does not exist
# ===========================================================================
@test "--setup warns when .env.local does not exist" {
    # Remove .env.local if it exists
    rm -f "${RECOVER_SH%/*}/.env.local"

    _write_mock crontab 'case "${1}" in -l) echo "*/10 * * * * '"${RECOVER_SH}"'" ;; *) exit 0 ;; esac'

    run env MOCK_BIN_DIR="${MOCK_BIN_DIR}" bash "${RECOVER_SH}" --setup
    [ "${status}" -eq 0 ]
    [[ "${output}" == *".env.local not found"* ]]
}

# ===========================================================================
# Test 11 — --setup does not duplicate cron entry when already installed
# ===========================================================================
@test "--setup does not duplicate cron entry when already installed" {
    # crontab -l already contains the recover.sh path
    _write_mock crontab 'case "${1}" in -l) echo "*/10 * * * * '"${RECOVER_SH}"'" ;; *) exit 0 ;; esac'

    run env MOCK_BIN_DIR="${MOCK_BIN_DIR}" bash "${RECOVER_SH}" --setup
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"already installed"* ]]
}

# ===========================================================================
# Test 12 — NAS not mounted → ensure_nas_mounted is called
# ===========================================================================
@test "calls ensure_nas_mounted when NAS is not mounted" {
    # mount returns nothing → NAS not mounted
    _write_mock mount "exit 0"
    # import NOT running
    _write_mock pgrep "exit 1"
    # Immich IS healthy
    _write_mock curl "exit 0"

    _run_recover
    [[ "${output}" == *"NAS not mounted"* ]]
    [[ "${output}" == *"mount.sh"* ]]
}

# ===========================================================================
# Test 13 — NAS mounted, import not running → start_import called (no full recovery)
# ===========================================================================
@test "starts import only when NAS mounted but import not running" {
    # NAS IS mounted (default mount mock)
    # import NOT running (default pgrep mock)
    # Immich IS healthy
    _write_mock curl "exit 0"

    _run_recover
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"Import not running — starting import"* ]]
    [[ "${output}" != *"FULL RECOVERY"* ]]
}

# ===========================================================================
# Test 14 — start_import fails when IMMICH_API_KEY is not set
# ===========================================================================
@test "start_import fails with error when IMMICH_API_KEY is not set" {
    # NAS IS mounted (default mount mock)
    # import NOT running (default pgrep mock)
    # Immich IS healthy
    _write_mock curl "exit 0"
    # Unset the API key
    export IMMICH_API_KEY=""

    _run_recover
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"IMMICH_API_KEY not set"* ]]
}

# ===========================================================================
# Test 15 — ensure_nas_mounted fails when mount.sh is absent
# ===========================================================================
@test "ensure_nas_mounted fails when mount.sh does not exist" {
    # NAS not mounted
    _write_mock mount "exit 0"
    # import NOT running (default pgrep mock)
    # Immich IS healthy
    _write_mock curl "exit 0"

    # Temporarily hide mount.sh
    local mount_sh="${RECOVER_SH%/*}/mount.sh"
    local backup="${mount_sh}.bak_$$"
    mv "${mount_sh}" "${backup}"

    _run_recover
    local rc="${status}"

    # Always restore before asserting (so a failure doesn't leave file missing)
    mv "${backup}" "${mount_sh}"

    [ "${rc}" -ne 0 ]
    [[ "${output}" == *"mount.sh not found"* ]]
}
