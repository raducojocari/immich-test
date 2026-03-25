# NFR-005 — Observability

| Field | Value |
|---|---|
| **ID** | NFR-005 |
| **Status** | Implemented |
| **Source** | CLAUDE.md project instructions |

## Description

Every operation must emit structured, levelled log output to both the terminal and a log file. Logs must be sufficient to diagnose failures after the fact without re-running the operation. Separate log files serve distinct purposes: operational logs for the current run, a persistent checkpoint log for import state, and a rolling recovery log for audit history.

## Behaviour

**Log levels and output:**
- All operations emit log lines at four levels: INFO (normal progress), WARN (non-fatal anomalies), ERROR (failures requiring attention). DEBUG/TRACE is available for detailed diagnostics.
- Every log line from shell scripts is timestamped in ISO 8601 format.
- Log output goes to both stdout (for interactive observation) and a log file (for post-mortem analysis).

**Operational log (cleared on each start):**
- Cleared at the beginning of each run so it contains only output from the most recent invocation.
- Receives all INFO, WARN, and ERROR messages for the current run.
- Stored under a `logs/` subdirectory.

**Import progress log (persistent, append-only):**
- Never cleared by the import process. Accumulates across all runs.
- Records every file outcome with a UTC timestamp and one of three status tokens: `CREATED`, `DUPLICATE`, or `FAILED` (with error detail).
- Also records import session start/end markers.
- Used by the checkpoint mechanism to skip already-processed files on re-run.
- Used by the recovery agent to detect a hung import (stale modification time).

**Recovery log (rolling, never cleared):**
- Retains the complete history of all recovery agent invocations and actions.
- Enables audit of when and why full recoveries were triggered.

**Import progress reporting:**
- Every 50 files processed, a progress summary line is emitted containing: files processed, files imported (created in Immich), duplicates detected, failures, upload rate (files per minute), and elapsed time.

## Acceptance Criteria

- After any failed run, the log file contains the first error message with enough context to identify the cause without re-running.
- The operational log is empty at the start of a run and contains only that run's output after it completes.
- The import progress log accumulates entries across multiple runs without losing prior entries.
- A progress summary line appears in the output after every 50 files processed.
- Shell script log lines include a timestamp and a level prefix (`[INFO]`, `[WARN]`, `[ERROR]`).
- Import log lines include per-file status (`[OK]`, `[SKIP]`, `[WARN]`) for created, duplicate, and failed files respectively.

## Constraints

- Log files are stored under a `logs/` directory relative to the script location.
- The import operational log is named `logs/import.log`; the persistent checkpoint log is named `import.log` (no subdirectory).
- The recovery operational log is named `logs/recover.log`.

## Related Requirements

- FR-005 — The checkpoint log and per-file outcome logging are defined in the import requirement.
- FR-006 — The recovery agent reads the checkpoint log's modification time and writes to its own rolling log.
- NFR-001 — Logging is what makes post-crash diagnosis and resume possible.
