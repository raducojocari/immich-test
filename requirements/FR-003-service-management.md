# FR-003 — Service Management

| Field | Value |
|---|---|
| **ID** | FR-003 |
| **Status** | Implemented |
| **Source** | Original user story |

## Description

The system provides dedicated start and stop operations for the Immich container stack. Both operations perform prerequisite checks before acting and give clear feedback on completion.

## Behaviour

**Start:**
- Verifies the container runtime is installed and its daemon is running.
- Verifies Immich has been installed (configuration files are present).
- Starts all containers in detached mode so the command returns immediately.
- On success, prints the URL at which the Immich web UI is accessible.

**Stop:**
- Verifies the same prerequisites as start.
- Stops all containers gracefully.
- On success, confirms that all persisted data (uploaded photos, database) is preserved and has not been deleted.

Both operations emit a meaningful error and exit with a non-zero status if any prerequisite is not met.

## Acceptance Criteria

- Start when container runtime is not installed → non-zero exit + error.
- Start when Docker daemon is not running → non-zero exit + error.
- Start when Immich is not installed (configuration files absent) → non-zero exit + error.
- Start happy path → containers running, web UI URL printed to stdout.
- Stop when Immich is not installed → non-zero exit + error.
- Stop happy path → containers stopped, data-preserved confirmation printed.
- Start/stop with a failing container runtime command → non-zero exit.

## Constraints

- Containers are started in detached mode; the command must not block waiting for containers to be fully ready.
- The container runtime command is overridable via environment variable for test isolation.

## Related Requirements

- FR-002 — Installation must have been completed before start/stop can be used.
- FR-004 — Reset calls stop before deleting data.
- FR-006 — The recovery agent calls stop and start as part of full recovery.
