#!/usr/bin/env bats
# test_mount.bats — Tests for output/mount.sh

load "helpers/common"

MOUNT_SH="${BATS_TEST_DIRNAME}/../output/mount.sh"

setup() {
    setup_test_env

    # Default mocks — represent a reachable, unmounted NAS
    _write_mock ping      "exit 0"
    _write_mock mount     "exit 0"    # returns nothing → NAS not yet mounted
    _write_mock showmount "exit 0"
    _write_mock ipconfig  "echo 192.168.1.100"
}

teardown() { teardown_test_env; }

_write_mock() {
    local name="$1" body="$2"
    cat > "${MOCK_BIN_DIR}/${name}" <<MOCK
#!/usr/bin/env bash
${body}
MOCK
    chmod +x "${MOCK_BIN_DIR}/${name}"
}

# Run mount.sh with MOUNT_TEST_MODE so the EUID/sudo check is bypassed
_run_mount() {
    run env \
        MOCK_BIN_DIR="${MOCK_BIN_DIR}" \
        MOUNT_TEST_MODE="1" \
        bash "${MOUNT_SH}" "$@" 2>&1
}

# ===========================================================================
# Test 1 — mount command uses soft option (prevents D-state NFS hangs)
# ===========================================================================
@test "mount command uses soft,timeo=50,retrans=2 to prevent D-state hangs" {
    cat > "${MOCK_BIN_DIR}/mount" <<'MOUNTMOCK'
#!/usr/bin/env bash
echo "mount invoked: $*"
exit 0
MOUNTMOCK
    chmod +x "${MOCK_BIN_DIR}/mount"

    _run_mount
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"soft"* ]]
    [[ "${output}" == *"timeo=50"* ]]
    [[ "${output}" == *"retrans=2"* ]]
}

# ===========================================================================
# Test 2 — mount command retains resvport option
# ===========================================================================
@test "mount command retains resvport option" {
    cat > "${MOCK_BIN_DIR}/mount" <<'MOUNTMOCK'
#!/usr/bin/env bash
echo "mount invoked: $*"
exit 0
MOUNTMOCK
    chmod +x "${MOCK_BIN_DIR}/mount"

    _run_mount
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"resvport"* ]]
}

# ===========================================================================
# Test 3 — exits 0 without remounting if already mounted
# ===========================================================================
@test "exits 0 without remounting when NAS is already mounted" {
    _write_mock mount "echo '//nas on /Volumes/nas (nfs)'"

    _run_mount
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"already mounted"* ]]
}

# ===========================================================================
# Test 4 — fails when NAS host is unreachable
# ===========================================================================
@test "fails when NAS host is unreachable" {
    _write_mock ping "exit 1"

    _run_mount
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"Cannot reach NAS"* ]]
}

# ===========================================================================
# Test 5 — fails when mount command fails
# ===========================================================================
@test "fails when mount command fails" {
    _write_mock mount "exit 1"

    _run_mount
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"Mount failed"* ]]
}
