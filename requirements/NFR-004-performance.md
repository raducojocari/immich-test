# NFR-004 — Upload Performance

| Field | Value |
|---|---|
| **ID** | NFR-004 |
| **Status** | Implemented |
| **Source** | Operational need — 150k+ file library, multi-day import |

## Description

The import pipeline must sustain high throughput over a long-running import of a large photo library without throughput degradation over time. This requires an efficient pipeline design that avoids per-file overhead and keeps the upload queue saturated.

## Behaviour

- No external process is spawned for each file. All file reading, metadata extraction, multipart encoding, and HTTP upload are performed within the import process itself, avoiding the overhead of launching child processes.
- HTTP connections to the media server are established once per worker thread and reused for all subsequent uploads on that thread. This eliminates TCP handshake overhead for every file.
- File discovery, checkpoint filtering, and upload submission are pipelined: the next batch of files is queued before the current batch finishes. Workers are kept busy continuously rather than waiting for a full batch to drain before refilling.
- Upload results are processed as each individual upload completes (first-completed ordering) rather than waiting for an entire batch to finish. This minimises idle time between uploads.
- The checkpoint filter is applied in O(n + m) time: the set of already-processed files is loaded once at startup, and the file discovery stream is filtered against it without re-reading the progress log for each file.

## Acceptance Criteria

- No subprocess (shell command, Python child process) is launched for each file during an import run.
- Upload throughput measured at the start of a run (first 1000 files) and at the end of a run (last 1000 files) does not differ by more than 20%.
- Worker threads are not left idle while files remain in the discovery stream.

## Constraints

- Performance must be achieved within the concurrency limits defined in NFR-003 (10 photo workers, 2 video workers).
- Throughput is bounded by NAS read speed, network bandwidth to the media server, and the server's ingest capacity — not by the import pipeline itself.

## Related Requirements

- NFR-003 — Concurrency limits cap throughput; the pipeline must saturate those limits efficiently.
- FR-005 — The import pipeline design is defined in the photo import requirement.
