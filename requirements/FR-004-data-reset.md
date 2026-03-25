# FR-004 — Data Reset

| Field | Value |
|---|---|
| **ID** | FR-004 |
| **Status** | Implemented |
| **Source** | Derived from operational needs |

## Description

The system provides a reset operation that wipes all Immich-managed data and import state, returning the system to a clean pre-import state. Because this operation is destructive and irreversible, it requires explicit user confirmation before proceeding.

## Behaviour

- The operation requires explicit confirmation before any data is deleted. Confirmation can be given either interactively (typing "yes" at a prompt) or non-interactively (passing a `--confirm` flag). If neither is provided, or if the interactive prompt receives any response other than "yes", the operation aborts without deleting anything.
- All containers are stopped before any data is deleted.
- The following are deleted: the Immich photo storage directory on the NAS, the database data directory on the local machine, and the import progress log.
- The following are preserved: the Immich configuration files (`.env`, compose files), and the original Google Photos source directory on the NAS.
- If any of the data directories to be deleted do not exist, the operation completes successfully — the absence of a directory is not an error.

## Acceptance Criteria

- Running without `--confirm` and entering anything other than "yes" at the prompt → aborts, prints "Aborted", no data deleted.
- Running without `--confirm` and receiving no input (piped empty stdin) → aborts, no data deleted.
- Running with `--confirm` → proceeds without prompting, all Immich data deleted.
- Data directories already absent → exits 0, no error.
- Configuration files (`.env`, compose files) are present and unchanged after a successful reset.
- Original Google Photos source directory is untouched after a successful reset.
- Container runtime not installed or daemon not running → non-zero exit before any deletion.
- Immich not installed → non-zero exit before any deletion.

## Constraints

- Confirmation must be impossible to bypass accidentally; there is no "quiet mode" that skips both interactive and flag-based confirmation.
- All paths are overridable via environment variables for test isolation.

## Related Requirements

- FR-003 — Stop is called as the first step of reset.
- FR-005 — The import progress log cleared by reset is the checkpoint used by the import operation.
- NFR-001 — After a reset followed by re-installation, the import can be started fresh with no stale state.
