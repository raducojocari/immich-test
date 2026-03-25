# NFR-001 — Resilience

| Field | Value |
|---|---|
| **ID** | NFR-001 |
| **Status** | Implemented |
| **Source** | Operational experience — long-running import over unreliable NFS |

## Description

The system tolerates failures at any layer — network, container runtime, NAS availability — and recovers without data loss or manual intervention. A large photo library import (150k+ files, multi-day duration) must survive crashes, reboots, and NAS outages and resume cleanly.

## Behaviour

- The import progress log is the single source of truth for what has been processed. No additional state files, databases, or lock files are required to resume. Re-running the import after any interruption automatically skips all previously processed files and continues with the remainder.
- All install, start, and stop operations are idempotent: running them more than once on an already-configured system produces the same result as running them once, without corrupting data or creating duplicate resources.
- The recovery agent monitors the system and applies targeted remediation: it remounts a dropped NAS volume, restarts a crashed import, or performs a full container/NAS cycle if the media server is unreachable — without human involvement.
- The NFS mount uses `soft` mode with bounded timeouts (`timeo=50,retrans=2`). This prevents kernel D-state hangs when the NFS server becomes unresponsive: I/O operations fail after ~15 seconds with `EIO`/`ETIMEDOUT` rather than blocking indefinitely. This is safe for read-only workloads such as photo import.
- Import failures for individual files (upload errors, connection resets) are recorded and do not halt the import. The `--failures` mode allows a targeted retry of only the files that previously failed, without re-processing files that succeeded.

## Acceptance Criteria

- Kill the import process mid-run, then restart it → only files not yet in the progress log are uploaded; previously processed files are skipped.
- NAS connection drops during import → affected uploads recorded as FAILED; import continues; recovery agent remounts and restarts within 10 minutes.
- Media server container crashes → recovery agent detects the unhealthy state within 10 minutes and performs full recovery.
- Run install twice on an already-installed system → no data corruption, no duplicate containers.
- Run start twice → second invocation is a no-op or succeeds without error.

## Constraints

- The progress log must never be truncated by the import process itself; it is append-only during a run.
- Recovery must not require a human to be present or monitoring the system.

## Related Requirements

- FR-005 — Checkpoint-based resumability is defined in the photo import requirement.
- FR-006 — The recovery agent is the automated resilience mechanism.
- NFR-005 — All recovery actions are logged so failures can be diagnosed after the fact.
