#!/usr/bin/env bash
# recover.sh — Automated recovery monitor for Immich.
# Runs as a foreground loop: checks infrastructure health, then runs the import
# in the foreground (output visible, Ctrl+C to stop).
# Run `recover.sh --setup` once to configure passwordless sudo for NAS operations.
# Run `recover.sh --once` to perform a single infrastructure check and exit.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_LOCAL="${SCRIPT_DIR}/.env.local"

# Source credentials if present
[[ -f "${ENV_LOCAL}" ]] && source "${ENV_LOCAL}"

# ---------------------------------------------------------------------------
# Configuration (overridable via environment)
# ---------------------------------------------------------------------------
IMMICH_URL="${IMMICH_URL:-http://localhost:2283}"
NAS_MOUNT_POINT="${NAS_MOUNT_POINT:-/Volumes/nas}"
IMMICH_PARALLEL="${IMMICH_PARALLEL:-10}"
IMMICH_VIDEO_PARALLEL="${IMMICH_VIDEO_PARALLEL:-2}"       # parallel count for video mode
IMMICH_WITH_VIDEO="${IMMICH_WITH_VIDEO:-false}"           # set to "true" to run import with --withvideo
CHECK_INTERVAL_SECS="${CHECK_INTERVAL_SECS:-10}"          # seconds to wait after import exits before restarting
RECOVER_MAX_ITERATIONS="${RECOVER_MAX_ITERATIONS:-0}"     # 0 = infinite; >0 for testing only
NAS_PROBE_TIMEOUT="${NAS_PROBE_TIMEOUT:-5}"               # seconds before declaring NFS hung
NAS_PROBE_CMD="${NAS_PROBE_CMD:-/bin/ls}"                 # probe command (overridable in tests)
NAS_WATCHDOG_INTERVAL="${NAS_WATCHDOG_INTERVAL:-30}"      # seconds between watchdog NFS probes
DOCKER_DOWN_TIMEOUT="${DOCKER_DOWN_TIMEOUT:-120}"         # seconds before giving up on docker compose down
DOCKER_UP_TIMEOUT="${DOCKER_UP_TIMEOUT:-60}"              # seconds before giving up on docker compose up
LOCK_FILE="/tmp/immich_recover.lock"
INSTALL_DIR="${SCRIPT_DIR}/install"
IMPORT_PID_FILE="${SCRIPT_DIR}/import.pid"

# Allow mock binary injection for tests
export PATH="${MOCK_BIN_DIR:+${MOCK_BIN_DIR}:}${PATH}"

# ---------------------------------------------------------------------------
# Logging — rolling (never cleared), written to stdout and log file
# ---------------------------------------------------------------------------
LOG_DIR="${SCRIPT_DIR}/logs"
LOG_FILE="${LOG_DIR}/recover.log"
mkdir -p "${LOG_DIR}"

log()  { local ts; ts="$(date '+%Y-%m-%dT%H:%M:%S')"; echo "${ts} [INFO]  $*" | tee -a "${LOG_FILE}"; }
warn() { local ts; ts="$(date '+%Y-%m-%dT%H:%M:%S')"; echo "${ts} [WARN]  $*" | tee -a "${LOG_FILE}"; }
err()  { local ts; ts="$(date '+%Y-%m-%dT%H:%M:%S')"; echo "${ts} [ERROR] $*" | tee -a "${LOG_FILE}" >&2; }

# ---------------------------------------------------------------------------
# Lock management — prevents two loop instances running simultaneously
# ---------------------------------------------------------------------------
acquire_lock() {
    if [[ -f "${LOCK_FILE}" ]]; then
        local old_pid
        old_pid="$(cat "${LOCK_FILE}")"
        if kill -0 "${old_pid}" 2>/dev/null; then
            log "Already running (PID=${old_pid}) — exiting."
            exit 0
        else
            warn "Stale lock (PID=${old_pid} dead) — removing and continuing."
            rm -f "${LOCK_FILE}"
        fi
    fi
    echo "$$" > "${LOCK_FILE}"
    trap 'rm -f "${LOCK_FILE}"' EXIT
}

# ---------------------------------------------------------------------------
# Infrastructure health checks (NAS + Immich only)
# ---------------------------------------------------------------------------
immich_is_healthy() {
    curl -sf --max-time 5 "${IMMICH_URL}/api/server/ping" >/dev/null 2>&1
}

nas_is_mounted() {
    mount | grep -q " on ${NAS_MOUNT_POINT} "
}

nas_is_responding() {
    # Probe the NAS mount with a bounded timeout.
    # NFS "not responding" keeps the mount table entry but hangs all I/O indefinitely.
    # Run the probe in a background subshell; declare failure if it exceeds NAS_PROBE_TIMEOUT.
    # Uses /bin/sleep (absolute path) so the timer is not affected by mock binaries in tests.
    ( ${NAS_PROBE_CMD} "${NAS_MOUNT_POINT}/" >/dev/null 2>&1 ) &
    local probe_pid=$!
    local i=0
    while kill -0 "${probe_pid}" 2>/dev/null && [[ "${i}" -lt "${NAS_PROBE_TIMEOUT}" ]]; do
        /bin/sleep 1
        i=$(( i + 1 ))
    done
    if kill -0 "${probe_pid}" 2>/dev/null; then
        kill -9 "${probe_pid}" 2>/dev/null || true
        warn "NAS probe timed out after ${NAS_PROBE_TIMEOUT}s — NFS server not responding"
        return 1
    fi
    wait "${probe_pid}" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Recovery actions
# ---------------------------------------------------------------------------
stop_import() {
    local pid=""
    if [[ -f "${IMPORT_PID_FILE}" ]]; then
        pid="$(cat "${IMPORT_PID_FILE}")"
        kill -0 "${pid}" 2>/dev/null || pid=""   # stale PID file — ignore
    fi
    if [[ -z "${pid}" ]]; then
        pid="$(pgrep -f "import\.py" 2>/dev/null || true)"
    fi
    if [[ -n "${pid}" ]]; then
        log "Stopping import process (PID=${pid})..."
        kill "${pid}" 2>/dev/null || true
        local i=0
        while kill -0 "${pid}" 2>/dev/null && [[ "${i}" -lt 15 ]]; do
            sleep 1
            i=$(( i + 1 ))
        done
        if kill -0 "${pid}" 2>/dev/null; then
            kill -9 "${pid}" 2>/dev/null || true
        fi
        log "Import process stopped."
    else
        log "No import process running."
    fi
}

_start_nas_watchdog() {
    # Background watchdog: periodically probes NFS while import runs in foreground.
    # If NFS hangs, kills the import to unblock the main loop so it can re-run
    # run_check() and trigger full recovery.
    # Traps SIGTERM to kill its internal sleep child so it leaves no orphaned processes.
    local import_pid_file="${IMPORT_PID_FILE}"
    (
        local _sleep_pid=""
        trap '[[ -n "${_sleep_pid}" ]] && kill "${_sleep_pid}" 2>/dev/null || true; exit 0' TERM
        while true; do
            /bin/sleep "${NAS_WATCHDOG_INTERVAL}" &
            _sleep_pid=$!
            wait "${_sleep_pid}" 2>/dev/null || break  # exits cleanly on SIGTERM
            if ! nas_is_responding 2>/dev/null; then
                warn "NAS watchdog: NFS not responding — force-unmounting NAS to wake D-state import"
                # D-state processes (stuck on NFS I/O) cannot be killed with SIGTERM/SIGKILL.
                # diskutil unmountDisk force is the macOS equivalent of "Disconnect All":
                # it removes the mount at the kernel level, waking all blocked processes.
                sudo diskutil unmountDisk force "${NAS_MOUNT_POINT}" 2>/dev/null || true
                local pid=""
                [[ -f "${import_pid_file}" ]] && pid="$(cat "${import_pid_file}")"
                if [[ -n "${pid}" ]]; then
                    kill "${pid}" 2>/dev/null || true
                else
                    pgrep -f "import\.py" 2>/dev/null | while IFS= read -r p; do
                        kill "${p}" 2>/dev/null || true
                    done
                fi
                exit 0  # watchdog exits after one trigger; loop will re-check health
            fi
        done
    ) &
    _WATCHDOG_PID=$!
}

start_import() {
    local import_script="${SCRIPT_DIR}/import.py"
    local api_key="${IMMICH_API_KEY:-}"
    if [[ -z "${api_key}" ]]; then
        err "IMMICH_API_KEY not set — add it to ${ENV_LOCAL}"
        return 1
    fi
    local parallel video_flag=""
    if [[ "${IMMICH_WITH_VIDEO:-false}" == "true" ]]; then
        parallel="${IMMICH_VIDEO_PARALLEL:-2}"
        video_flag="--withvideo"
        log "Starting import (video mode, IMMICH_VIDEO_PARALLEL=${parallel})..."
    else
        parallel="${IMMICH_PARALLEL:-10}"
        log "Starting import (IMMICH_PARALLEL=${parallel})..."
    fi
    # Run in the foreground — output is visible in the terminal, attached to this session
    env IMMICH_API_KEY="${api_key}" IMMICH_PARALLEL="${parallel}" \
        python3 -u "${import_script}" --all ${video_flag}
}

wait_for_immich() {
    log "Waiting for Immich to become healthy..."
    local i=0
    while [[ "${i}" -lt 24 ]]; do
        if immich_is_healthy; then
            log "Immich is healthy."
            return 0
        fi
        sleep 5
        i=$(( i + 1 ))
    done
    err "Immich did not become healthy within 120 seconds."
    return 1
}

# Run a docker compose command with a time limit.
# Uses a background subshell + manual timer (macOS has no GNU timeout).
# Returns 0 if the command completed in time, 1 if it was killed.
_run_docker_with_timeout() {
    local timeout_secs="$1"
    shift
    ( docker compose "$@" ) &
    local _dc_pid=$!
    local i=0
    while kill -0 "${_dc_pid}" 2>/dev/null && [[ "${i}" -lt "${timeout_secs}" ]]; do
        /bin/sleep 1
        i=$(( i + 1 ))
    done
    if kill -0 "${_dc_pid}" 2>/dev/null; then
        warn "docker compose timed out after ${timeout_secs}s — killing"
        kill "${_dc_pid}" 2>/dev/null || true
        /bin/sleep 2
        kill -9 "${_dc_pid}" 2>/dev/null || true
        wait "${_dc_pid}" 2>/dev/null || true
        return 1
    fi
    wait "${_dc_pid}"
}

full_recovery() {
    warn "=== FULL RECOVERY starting ==="
    local mount_script="${SCRIPT_DIR}/mount.sh"

    # 1. Stop any running import process (SIGTERM → wait → SIGKILL)
    stop_import

    # 2. Stop all containers
    log "Stopping containers..."
    if ! _run_docker_with_timeout "${DOCKER_DOWN_TIMEOUT}" --project-directory "${INSTALL_DIR}" down; then
        warn "docker compose down timed out — continuing recovery anyway"
    fi

    # 3. Force-unmount NAS (non-blocking, macOS-compatible)
    log "Force-unmounting NAS at ${NAS_MOUNT_POINT}..."
    sudo diskutil unmountDisk force "${NAS_MOUNT_POINT}" 2>/dev/null || true

    # 4. Remount NAS
    if [[ ! -f "${mount_script}" ]]; then
        err "cannot remount NAS — ${mount_script} not found"
        return 1
    fi
    log "Remounting NAS..."
    if ! sudo "${mount_script}"; then
        err "cannot remount NAS — ${mount_script} failed"
        return 1
    fi

    # 4b. Verify NAS is actually responding after remount (prevents docker compose hanging on NFS volume)
    log "Verifying NAS responsiveness after remount..."
    if ! nas_is_responding; then
        err "NAS not responding after remount — aborting recovery (loop will retry)"
        return 1
    fi

    # 5. Start containers
    log "Starting containers..."
    if ! _run_docker_with_timeout "${DOCKER_UP_TIMEOUT}" --project-directory "${INSTALL_DIR}" up --detach; then
        err "docker compose up timed out — aborting recovery (loop will retry)"
        return 1
    fi

    # 6. Wait for media server to become healthy (up to 120 seconds)
    wait_for_immich || return 1

    warn "=== FULL RECOVERY complete ==="
}

# ---------------------------------------------------------------------------
# Infrastructure health check — checks NAS + Immich only
# Import process is managed by the main loop, not by this check.
# ---------------------------------------------------------------------------
run_check() {
    local _immich _nas
    immich_is_healthy && _immich=yes || _immich=no

    if nas_is_mounted && nas_is_responding; then
        _nas=yes
    else
        _nas=no
    fi

    log "Health check: immich=${_immich} nas=${_nas}"

    if [[ "${_immich}" == yes ]] && [[ "${_nas}" == yes ]]; then
        log "All healthy — starting import."
        return 0
    fi

    warn "Unhealthy state detected — triggering full recovery."
    full_recovery
}

# ---------------------------------------------------------------------------
# Setup sub-command — configures passwordless sudo for NAS operations
# ---------------------------------------------------------------------------
run_setup() {
    log "Running setup for recover.sh..."

    # Write passwordless sudoers entry for NAS operations (diskutil + mount.sh only)
    local sudoers_file="/etc/sudoers.d/immich_recover"
    local sudoers_line="${USER} ALL=(root) NOPASSWD: /usr/sbin/diskutil, ${SCRIPT_DIR}/mount.sh"
    log "Writing sudoers entry to ${sudoers_file}..."
    echo "${sudoers_line}" | sudo tee "${sudoers_file}" >/dev/null
    sudo chmod 0440 "${sudoers_file}"
    log "sudoers entry written for diskutil and mount.sh."

    # Warn if credentials file is missing
    if [[ ! -f "${ENV_LOCAL}" ]]; then
        warn ".env.local not found — create ${ENV_LOCAL} with IMMICH_API_KEY=<your-key>"
    fi

    log "Setup complete."
}

# ===========================================================================
# Main
# ===========================================================================
if [[ "${1:-}" == "--setup" ]]; then
    run_setup
    exit 0
fi

acquire_lock

if [[ "${1:-}" == "--once" ]]; then
    # Infrastructure check only — does not start the import
    run_check
    exit $?
fi

# Foreground loop — checks infrastructure, then runs import in the foreground.
# Import output is visible in this terminal session. Ctrl+C stops everything.
log "Recovery monitor started. Import will run in the foreground (Ctrl+C to stop)."
_iter=0
_WATCHDOG_PID=""
while true; do
    run_check || true   # check NAS + Immich; perform full recovery if needed

    _start_nas_watchdog
    start_import || warn "Import exited with non-zero status."
    kill "${_WATCHDOG_PID}" 2>/dev/null || true
    wait "${_WATCHDOG_PID}" 2>/dev/null || true

    log "Import finished. Next check in ${CHECK_INTERVAL_SECS}s..."
    _iter=$(( _iter + 1 ))
    if [[ "${RECOVER_MAX_ITERATIONS}" -gt 0 ]] && [[ "${_iter}" -ge "${RECOVER_MAX_ITERATIONS}" ]]; then
        break
    fi
    sleep "${CHECK_INTERVAL_SECS}"
done
