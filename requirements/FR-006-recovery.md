# FR-006 — Automated Recovery

| Field | Value |
|---|---|
| **ID** | FR-006 |
| **Status** | Implemented |
| **Source** | Derived from operational stability requirements |

## Description

The system includes a recovery monitor that runs as a foreground loop in an interactive terminal session. On each iteration it checks infrastructure health (NAS + media server), performs a full recovery if anything is wrong, then runs the import process in the foreground. The import output is fully visible in the terminal; Ctrl+C stops both the import and the monitor. The agent is started explicitly by the operator and remains attached to the terminal, making its activity visible and its lifecycle explicit.

The environment is treated as inherently unreliable: network connections are flaky, dependencies disconnect for unpredictable reasons, and it is impossible to enumerate every failure mode in advance. Because partial remediation leaves the system in an unknown state and risks masking deeper problems, the response to any infrastructure anomaly is always the same complete recovery cycle.

## Behaviour

**Foreground loop (default mode):**

Each iteration of the loop:
1. Check infrastructure health (NAS mounted + media server responding).
2. If unhealthy → trigger full recovery.
3. Run the import process in the foreground (blocking; output visible in terminal).
4. When the import exits (for any reason) → log "Import finished", wait `CHECK_INTERVAL_SECS` (default 10 s), then repeat from step 1.

**Health assessment (`--once` mode and each loop iteration):**

The infrastructure is healthy if and only if both of the following are true simultaneously:

- The media server responds to a health check.
- The NAS is mounted **and responding to I/O** within `NAS_PROBE_TIMEOUT` seconds (default 5 s).

The NAS check has two parts: (1) the mount table entry exists, and (2) a bounded probe command (`NAS_PROBE_CMD`, default `/bin/ls`) completes within the timeout. This detects the macOS "nfs server not responding" condition, where the mount entry remains present but all I/O hangs indefinitely in kernel D-state.

If both conditions pass → no recovery triggered. In loop mode, import is started immediately after. In `--once` mode, the script exits 0.

If **any** condition fails → trigger full recovery. There are no partial or targeted fixes. The recovery response is the same regardless of which condition failed or why.

**Full recovery sequence:**

1. Stop any running import process (SIGTERM, wait up to 15 seconds, then SIGKILL if still alive). The import process is identified via a PID file (`import.pid` in the script directory), written by `import.py` at startup, with a `pgrep` fallback for processes started without PID file support.
2. Stop all containers.
3. Force-unmount the NAS (non-blocking unmount appropriate for macOS).
4. Remount the NAS.
5. Start all containers.
6. Wait for the media server to become healthy, polling every 5 seconds for up to 120 seconds.

After full recovery, in loop mode the import is started by the main loop (not by the recovery sequence itself).

**Background NFS watchdog (loop mode only):**

While the import runs in the foreground (blocking the main loop), a background watchdog process periodically runs the same NFS probe (every `NAS_WATCHDOG_INTERVAL` seconds, default 30 s). If the probe fails, the watchdog:

1. Calls `sudo diskutil unmountDisk force` to perform a kernel-level forced unmount. This is necessary because NFS-hung processes are in kernel **D-state** (uninterruptible sleep), and D-state processes cannot receive any signal — including SIGKILL — until the NFS mount is removed. This step is the automated equivalent of clicking "Disconnect All" in the macOS NFS dialog.
2. Kills the import process (now woken from D-state and killable).

After the import exits, `start_import()` returns, the main loop continues, `run_check()` detects the NAS is no longer mounted, and full recovery fires (remount + container restart). The watchdog exits after triggering once and is restarted on the next loop iteration. On normal import completion, the main loop sends SIGTERM to the watchdog before continuing.

**`--once` mode:**

Performs a single infrastructure check and exits. Does not start the import. Useful for health probing and testing.

**Concurrency protection:**

- Only one instance runs at a time. At startup the agent acquires a lock using the current process ID. If a valid lock from a live process already exists, the new invocation exits immediately.
- If a lock file exists but references a process that is no longer alive (crashed agent), the stale lock is removed and the agent proceeds normally.

**Setup sub-command:**

- A `--setup` sub-command configures passwordless `sudo` for the NAS unmount and remount operations. This must be run once before starting the agent so that NAS operations do not prompt for a password.

**Logging:**

- All actions and decisions are logged with timestamps and severity levels.
- The recovery log is rolling and is never cleared, preserving the history of all recovery events.

## Acceptance Criteria

- NAS mounted + responding + media server healthy → no full recovery triggered; import started in loop mode.
- Media server health check fails → full recovery triggered.
- NAS not mounted → full recovery triggered (not a targeted mount-only action).
- NAS mounted but NFS not responding (probe times out or fails) → full recovery triggered.
- `--once`: infrastructure healthy → exits 0, import NOT started.
- `--once`: infrastructure unhealthy → full recovery triggered, exits with recovery result.
- Two concurrent invocations while first is still running → second exits immediately with "already running" message.
- Lock file present with dead PID → stale lock cleaned up, agent continues.
- `--setup` → passwordless sudo configured for NAS operations.
- Full recovery: if media server does not become healthy within 120 seconds after restart → exits with error.
- Import process stopped via PID file during full recovery when PID file contains live PID.
- Import process stopped via pgrep fallback when PID file contains dead/missing PID.
- Import stuck on NFS hang (D-state) → watchdog force-unmounts NAS via `diskutil`, import wakes and exits, full recovery follows — no manual "Disconnect All" required.

## Constraints

- The agent checks only NAS mount status and media server health. Import process health is not a recovery trigger; the foreground loop restarts the import naturally when it exits.
- The agent cannot predict all failure modes. When in doubt it always performs a full recovery rather than attempting a targeted fix.
- There are no partial remediation paths. Any infrastructure anomaly triggers the complete recovery sequence.
- The agent requires `sudo` access for NAS operations; this must be pre-configured via `--setup` before starting the agent.
- API key and environment variables are read from a local credentials file; no credentials are passed on the command line.
- To restart the import in video mode after recovery, set `IMMICH_WITH_VIDEO=true` in `.env.local`. Without this, the import always runs in photo mode (`--all` without `--withvideo`).
- `CHECK_INTERVAL_SECS` (default 10 s) controls the pause between import exit and the next health check in loop mode.
- `NAS_PROBE_TIMEOUT` (default 5 s): seconds the NFS probe is allowed before declaring the NAS unresponsive.
- `NAS_WATCHDOG_INTERVAL` (default 30 s): seconds between watchdog NFS probes while import runs.
- `NAS_PROBE_CMD` (default `/bin/ls`): the probe command executed against the NAS mount point; overridable for testing.

## Related Requirements

- FR-001 — NAS mount and unmount are steps within full recovery.
- FR-003 — Container start/stop are steps within full recovery.
- FR-005 — The import process is started and monitored by the recovery agent.
- NFR-001 — The recovery agent is the automated resilience mechanism for infrastructure failures.
- NFR-008 — Sudo grants for NAS operations must be scoped to minimum required binaries.
