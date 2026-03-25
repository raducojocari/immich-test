# FR-001 — NAS Mount

| Field | Value |
|---|---|
| **ID** | FR-001 |
| **Status** | Implemented |
| **Source** | Original user story |

## Description

The system must be able to mount the Unifi NAS over NFS so that photo source files and Immich storage are accessible on the local machine. Mounting requires elevated privileges and involves several safety checks to avoid silent failures when the NAS is unreachable or the machine is not authorised.

## Behaviour

- Mounting requires administrator privileges. If the current process does not have them, the system re-invokes itself with elevated privileges automatically, without requiring the user to prefix commands manually.
- Before attempting to mount, the system verifies the NAS is network-reachable. If it is not, the operation exits immediately with a clear error message.
- If the calling machine's IP address is not in the NAS's allowed-client list, the system surfaces the machine's current IP address and instructs the user to add it to the NFS export configuration, then exits without attempting the mount.
- If the NAS is already mounted at the configured mount point, the operation exits successfully without performing a duplicate mount.
- The mount uses NFS version 3 with options appropriate for macOS (`resvport`).
- On success the NAS filesystem is accessible at the configured mount point (default: `/Volumes/nas`).

## Acceptance Criteria

- Running mount when the NAS device is network-unreachable → non-zero exit code + actionable error message.
- Running mount when the machine's IP is not in the NAS whitelist → non-zero exit code + current IP shown in the error message.
- Running mount when NAS is already mounted → exits 0, no duplicate entry in the mount table.
- Running mount with all prerequisites satisfied → NAS filesystem accessible at the mount point.

## Constraints

- The mount point is configurable; the default is `/Volumes/nas`.
- The NAS IP address, NFS export path, and mount options are fixed to the specific Unifi NAS hardware in this deployment.
- The operation must not hang indefinitely; network checks use short timeouts.

## Related Requirements

- FR-002 — Installation verifies the NAS is mounted before proceeding.
- FR-006 — The recovery agent remounts the NAS as part of full recovery.
- NFR-008 — Passwordless sudo for the mount operation must be scoped to the minimum required binary.
