# NFR-003 — NAS and Container I/O Protection

| Field | Value |
|---|---|
| **ID** | NFR-003 |
| **Status** | Implemented |
| **Source** | Operational experience — NAS overload and Docker VirtioFS saturation |

## Description

Upload concurrency and file size are bounded to prevent the NAS NFS server and the Docker container filesystem layer from becoming overwhelmed during a large import. These limits were derived from observed failures in production and must be respected by any implementation.

## Behaviour

- The number of simultaneous photo uploads is limited. The default limit is 10 concurrent uploads; this is configurable via an environment variable (`IMMICH_PARALLEL`).
- Video uploads use a stricter default limit of 2 concurrent uploads due to larger file sizes; this is separately configurable (`IMMICH_VIDEO_PARALLEL`).
- Files at or above a configurable size threshold (default 99 MB) are skipped with a warning rather than uploaded. This prevents large sequential reads from saturating the NAS I/O bandwidth. The threshold is configurable (`IMMICH_LARGE_MB`).
- The deployed container configuration includes explicit CPU and memory resource limits for each service to prevent the import workload from consuming all host resources:
  - Media server: 6 CPU cores, 3 GB RAM.
  - Machine learning service: 4 CPU cores, 3 GB RAM.
  - Database: 2 CPU cores, 1 GB RAM.

## Acceptance Criteria

- At no point during a photo import do more than `IMMICH_PARALLEL` (default 10) upload operations run simultaneously.
- At no point during a video import do more than `IMMICH_VIDEO_PARALLEL` (default 2) upload operations run simultaneously.
- Any file at or above `IMMICH_LARGE_MB` MB → skipped with a warning message, not counted as a failure, not uploaded.
- The deployed container configuration contains explicit resource limits for each named service.
- Setting `IMMICH_PARALLEL=3` limits concurrency to 3 for the duration of the run.

## Constraints

- The default limits (10 photo, 2 video, 99 MB) reflect the maximum safe values observed in production with a Unifi NAS under NFS v3. Raising them may cause NAS overload or VirtioFS saturation.
- Resource limits are set at deployment time; changing them requires re-deploying the container stack.

## Related Requirements

- FR-002 — Container resource limits are configured during installation.
- FR-005 — Upload concurrency and size filtering are part of the import pipeline.
- NFR-004 — Concurrency limits and the pipeline design work together to sustain throughput without overloading the NAS.
