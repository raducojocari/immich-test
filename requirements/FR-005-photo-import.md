# FR-005 — Photo Import

| Field | Value |
|---|---|
| **ID** | FR-005 |
| **Status** | Implemented |
| **Source** | Original user story |

## Description

The system transfers Google Photos Takeout archives from the NAS into the Immich media library via the Immich REST API. The import is resumable after any interruption, supports multiple operating modes, and records the outcome of every file in a persistent progress log.

## Behaviour

**Startup validation:**
- The system checks that an API key is configured and that the photo source directory exists before attempting any uploads. Either missing condition causes an immediate exit with a descriptive error.
- The system verifies the media server is reachable and the API key is valid. If the server is temporarily unavailable (e.g. just restarted), it retries for up to 60 seconds before giving up.

**Operating modes:**
- `--test` (default): uploads a small sample (default 5 files) to verify connectivity and configuration.
- `--all`: uploads the entire library.
- `--failures`: retries only files that were previously recorded as failed in the progress log.
- `--withvideo`: operates on video files instead of photo files; can be combined with any of the above modes.

**Resumability:**
- On each run, the system reads the persistent progress log and skips any file that was previously recorded as successfully created or a duplicate. This allows the import to be interrupted at any point (crash, manual kill, network outage) and restarted, with only the remaining files uploaded.

**File handling:**
- Photo files larger than `IMMICH_LARGE_MB` (default 99 MB) or video files larger than `IMMICH_VIDEO_LARGE_MB` (default 4096 MB) are skipped with a warning and counted separately.
- For each file, the creation timestamp is sourced from a Google Takeout JSON sidecar file if one is present (fields: `photoTakenTime`, then `creationTime`), falling back to the file's own modification time.
- Each upload is attempted up to 3 times on connection failure before the file is recorded as failed.
- A failed upload does not stop the import; the system continues with the remaining files.

**Progress and logging:**
- A progress summary is emitted every 50 files showing: files processed, imported, duplicates, failures, upload rate (files/min), and elapsed time.
- Every file outcome is appended to a persistent progress log with a UTC timestamp and one of three status tokens: `CREATED`, `DUPLICATE`, or `FAILED` (with error detail).
- An operational log (cleared at the start of each run) receives all INFO, WARN, and ERROR messages for the current run.

**Exit behaviour:**
- Exits 0 if all attempted uploads succeeded (no failures).
- Exits 1 if any file ended in a FAILED state.

## Acceptance Criteria

- Missing API key → exits 1 before any uploads, error message references where to set the key.
- Source directory absent → exits 1 before any uploads.
- Server unreachable after 60 seconds of retrying → exits 1.
- API key invalid → exits 1.
- File already in progress log as CREATED or DUPLICATE → skipped with no network request made.
- File at or above the size limit → skipped with a warning, not counted as a failure.
- JSON sidecar present with `photoTakenTime` → that timestamp used as the file's creation date in Immich.
- `--test` mode → at most 5 files uploaded.
- `--failures` mode → only files with FAILED entries in the progress log are attempted.
- `--withvideo` → only video extensions processed; photos ignored.
- Any upload failure → recorded as FAILED in progress log, import continues with remaining files.
- Progress line emitted every 50 files.
- Kill import mid-run, restart → only files not yet in progress log are uploaded.
- All uploads succeed → exits 0.
- Any upload fails → exits 1.

## Constraints

- Concurrent photo uploads default to 10; concurrent video uploads default to 2. Both are configurable.
- The size limit, test sample count, and all directory/URL settings are configurable via environment variables: `IMMICH_LARGE_MB=99` (photo size cap in MB), `IMMICH_VIDEO_LARGE_MB=4096` (video size cap in MB).
- The progress log is append-only and must never be truncated by the import process itself.

## Related Requirements

- FR-001 — NAS must be mounted for the source directory to be accessible.
- FR-004 — Reset clears the progress log, enabling a fresh import.
- FR-006 — The recovery agent monitors the progress log's modification time to detect a hung import.
- FR-007 — User profiles extend this requirement to support per-user API keys and source directories.
- NFR-001 — Resumability is the primary resilience mechanism for import.
- NFR-003 — Upload concurrency limits protect the NAS and container filesystem.
- NFR-004 — The pipeline is optimised for sustained throughput over large libraries.
- NFR-005 — All outcomes are logged with structured, levelled output.
