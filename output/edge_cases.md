# Import Edge Cases

_Generated from `output/import.log`. Last updated: 2026-03-17 06:45 (run in progress)_

---

## Edge Case 1: Immich upload storage corruption (ENOTDIR) — RESOLVED

**Occurrences:** 1045+ _(runs 2026-03-15 22:19 through 2026-03-16 20:24)_

**Log signature:**
```
FAILED    <rel_path> — HTTP 500
```

**Root cause:** Hash bucket path components (`c9`, `ea`) existed as files instead of
directories under `/data/upload/72b5a5e8-787b-4dd8-877a-d4e59c4b0d31/`, causing
Immich's `mkdirSync` to throw `ENOTDIR` → HTTP 500 on every upload.

**Status:** RESOLVED. Corrupt nodes removed. Run `2026-03-16 20:33` is uploading
successfully — CREATED entries appearing as expected.

---

## Edge Case 2: NAS file read error during upload

**Occurrences:** 14 _(run 2026-03-16 20:18 — transient, resolved in next run)_

**Log signature:**
```
FAILED    <rel_path> — read error
```

Transient NAS access blip. Same files attempted in the following run got HTTP 500
(ENOTDIR) instead. Not a recurring issue.

---

## Edge Case 3: File not found at upload time (ENOENT)

**Occurrences:** 293 _(run 2026-03-15 22:01 — resolved)_

Stale `filelist.cache` or transient NFS mount drop. Resolved.

---

## Edge Case 4: Upload connection failure after 3 retries

**Occurrences:** 3 _(run 2026-03-15 22:01 — resolved)_

Brief transient Docker/Immich pause. Resolved.

---

## Edge Case 5: Upload connection failure — HTTP 000

**Occurrences:** 677 _(ongoing — last seen 2026-03-17T06:45:28Z)_

**Log signature:**
```
FAILED    <rel_path> — HTTP 000
```

**Root cause:** HTTP 000 means no response received from Immich after 3 retries — connection
refused, socket timeout, or NFS mount degradation causing reads to hang/drop mid-upload.
Auto-remount triggers every 10 occurrences (requires `NAS_REMOTE` env var).
All FAILED files will be retried on the next run (not checkpointed as done).

**Status:** Active — 677 failures. NAS connection is intermittently dropping under load.

---

## Summary

| Edge case | Occurrences | Status |
|-----------|-------------|--------|
| Immich ENOTDIR storage corruption | 1045+ | Resolved |
| NAS file read error (transient) | 14 | Resolved |
| File not found (ENOENT) | 293 | Resolved |
| Connection failure (3 retries) | 3 | Resolved |
| Upload connection failure (HTTP 000) | **677** | **Active** |

**Current run (2026-03-17 06:45):** 677 HTTP 000 failures — NAS intermittently dropping.
Auto-remount active (every 10 failures). All failed files retry on next run.
