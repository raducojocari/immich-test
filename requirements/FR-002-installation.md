# FR-002 — Installation

| Field | Value |
|---|---|
| **ID** | FR-002 |
| **Status** | Implemented |
| **Source** | Original user story |

## Description

The system provides a single-command installer that downloads the official Immich container stack, applies the minimal local configuration needed for this deployment (NAS storage paths, external library mount, container resource limits), and starts all services. The installer validates all prerequisites before making any changes.

## Behaviour

- Before making any changes, the system checks that all prerequisites are present: a container runtime (Docker) is installed and its daemon is running, the Docker Compose plugin is available, an HTTP download tool (curl) is present, the NAS is mounted, and the Google Photos source directory exists at the expected path on the NAS.
- Any failed prerequisite causes an immediate exit with a message that names the missing component and suggests how to resolve it.
- Configuration is downloaded from the official Immich release channel. The system makes only the minimum changes required for this deployment and preserves all other Immich defaults, so that upgrading Immich in the future requires minimal effort.
- Photo storage (uploaded media) is placed on the NAS under a dedicated subdirectory so that storage capacity scales with the NAS.
- Database storage is placed locally (on the host machine) rather than on the NAS to avoid NFS-related database corruption.
- The container stack is configured with resource limits (CPU and memory per container) to prevent the import workload from making the host machine unresponsive.
- An external library volume is configured so that Immich can read directly from the Google Photos source folder on the NAS.
- On successful completion, all containers are running and the web UI is accessible.

## Acceptance Criteria

- Container runtime absent → non-zero exit + message suggesting how to install Docker.
- Docker daemon not running → non-zero exit + message suggesting how to start it.
- Docker Compose plugin absent → non-zero exit + message suggesting how to update Docker.
- HTTP download tool absent → non-zero exit + message suggesting how to install it.
- NAS not mounted → non-zero exit.
- Google Photos source directory absent on the NAS → non-zero exit showing the expected path.
- Download of official configuration files fails → non-zero exit.
- Happy path → all containers running, web UI accessible at `http://localhost:2283`, photo storage on NAS, database storage local.

## Constraints

- The installer must not deviate significantly from the official Immich configuration in order to remain maintainable across Immich version upgrades.
- All paths and command names are overridable via environment variables so that the installer can be tested without touching real infrastructure.
- The operation is idempotent: running it more than once on an already-installed system does not corrupt existing data.

## Related Requirements

- FR-001 — NAS must be mounted before installation can proceed.
- FR-003 — Start/stop rely on the configuration files written by the installer.
- FR-004 — Reset relies on the paths configured during installation.
- NFR-003 — Container resource limits are set during installation.
- NFR-006 — All installation paths are overridable for test isolation.
