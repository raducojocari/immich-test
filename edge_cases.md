# Import Edge Cases

Sources: `output/import.log` (checkpoint) and `output/logs/import.log` (last run).
Total entries in checkpoint: 0 (fresh start after factory reset — previous 976 uploads lost).

---

| # | Edge Case | Occurrences |
|---|-----------|-------------|
| 1 | File skipped — exceeds 99 MB size limit | 915 |
| 2 | Upload failed — connection reset after 3 attempts (HTTP 000) | 19 |
| 3 | Docker Desktop crash — VirtioFS saturation kills the VM process | 3 |
| 4 | NAS directory walk hangs — `os.walk()` over VirtioFS stalls for 15+ minutes | 1 |
| 5 | Stale file cache — test suite wrote temp paths into production `filelist.cache` | 3 |
| 6 | NFS server not responding — NAS at 192.168.1.253 went unresponsive mid-upload | 2 |
| 7 | Prechecker silent for 9 minutes — SHA1-hashing 150,886 files over NFS with no log output | 1 |
| 8 | NAS sync-write setting change caused mid-run service interruption | 1 |

---

## 1. File skipped — exceeds 99 MB size limit

**Occurrences:** 915 (full dataset — all 166 dirs across all 15 takeout archives;
previously undercounted at 24 because earlier runs only scanned one archive)

**What happens:** `find_media_files()` calls `os.path.getsize()` before yielding. Any file
≥ `LARGE_FILE_MB × 1 MiB` is skipped with a WARNING and never queued for upload. Because
the file is never checkpointed, every re-run re-skips it indefinitely.

**Potential causes:**
- `IMMICH_LARGE_MB` defaults to 99, a threshold sized for photo imports. All 915 skipped
  files are videos (.mp4 / .MOV) spread across all 15 takeout archives.
- Concentrated in `Antalya 2022` albums. Total library: 150,886 media files of which
  915 (0.6%) are oversized videos awaiting a dedicated `--withvideo` pass.

**To recover:** Re-run with a higher limit after the video pass is stable:
```
IMMICH_LARGE_MB=500 python3 output/import.py --all --withvideo
```

---

## 2. Upload failed — connection reset after 3 attempts (HTTP 000)

**Occurrences:** 14 (4 from video runs + 10 new from photo run at `21:12:21–27`)

**What happens:** The script retries each upload up to 3 times, resetting `_local.conn`
on each failure. HTTP 000 means the TCP connection was dropped before the server returned
any response. All 3 retries exhausted without recovery, so the file is logged as FAILED
in the checkpoint and will be retried on the next run.

**Potential causes:**
- **Videos (4 occurrences):** VirtioFS saturation during large concurrent video reads.
- **Photos (10 occurrences):** 10 `.jpg` files from `Family & friends` all failed within
  a 6-second window (`21:12:21–27`), suggesting a brief server-side drop rather than
  per-file I/O saturation. Likely causes: Docker `AutoPauseTimeoutSeconds=300` kicking in
  after 5 minutes of idle (cache build took ~3.5 min, then uploads started), or Immich
  briefly overloaded as 10 parallel connections hit simultaneously.

**Affected photo files (new):**
- `Family & friends/20220206_120349.jpg`
- `Family & friends/20220204_080342.jpg`
- `Family & friends/20220202_071213.jpg`
- `Family & friends/20220201_122327.jpg` + 6 others in same album/minute

**To recover:** Re-run — checkpoint will skip already-uploaded files and retry only failed ones:
```
python3 output/import.py --all
```

---

## 3. Docker Desktop crash — VirtioFS saturation kills the VM process

**Occurrences:** 2 (at `20:12:14` and `20:31:46` on 2026-03-15)

**What happens:** The Docker Desktop parent process crashes mid-import. The VM watchdog
detects `parent process disappeared` and attempts auto-restart, but macOS Virtualization
Framework rejects it with `Invalid virtual machine configuration. The storage device
attachment is invalid.` because the previous VirtioFS session did not shut down cleanly.
All subsequent restart attempts fail with the same error until a full Docker Desktop
reset is performed.

**Contributing settings confirmed from crash report:**
- `UseVirtualizationFrameworkVirtioFS:true` — VirtioFS is the active file sharing driver
- `FilesharingDirectories:[/Users /Volumes /private /tmp /var/folders]` — `/Volumes` (NAS
  mount) is shared into the VM via VirtioFS; every file read goes through this path
- `UseGrpcfuse:true` — gRPC FUSE also enabled alongside VirtioFS, adding I/O overhead
- `MemoryMiB:8092` / `SwapMiB:1024` — 8 GB RAM with only 1 GB swap; large video files
  read entirely into memory before upload; under parallel load this exhausts headroom
- `UseResourceSaver:true` / `AutoPauseTimeoutSeconds:300` — resource saver may throttle
  or pause the VM during sustained I/O, compounding instability
- `NetworkType:gvisor` — gVisor user-space networking adds a further layer between the
  upload TCP stream and the host, increasing sensitivity to I/O stalls

**Failure chain:**
1. Importer reads large video files from NAS via `/Volumes` → VirtioFS → Linux VM
2. Concurrent reads saturate the VirtioFS I/O queue
3. Docker Desktop host process crashes (`watchdog detected parent process disappeared`)
4. Auto-restart fails: VirtioFS attachment left in invalid state by unclean shutdown
5. Containers become completely unresponsive; requires Docker Desktop factory reset

**To prevent:**
- Run video imports with `IMMICH_PARALLEL=2` to keep VirtioFS I/O below saturation
- Consider switching from VirtioFS to gRPC FUSE (`UseVirtualizationFrameworkVirtioFS:false`)
  in Docker Desktop settings — gRPC FUSE is slower but more stable under sustained load
- Disable `UseResourceSaver` during import runs to prevent the VM being throttled mid-upload

---

## 4. NAS directory walk hangs — `os.walk()` over VirtioFS stalls for 15+ minutes

**Occurrences:** 1 (2026-03-15, run started at `20:42:57`, still walking at `20:58+`)

**What happens:** `find_media_files()` calls `os.walk(PHOTOS_DIR)` which must enumerate
every file in the entire Takeout archive before the checkpoint filter, prechecker, or any
upload can begin. Over VirtioFS with a large NAS archive the kernel has to make a FUSE
round-trip for every directory entry. The log stays frozen at 9 lines the entire time.
As a side effect, the sustained VirtioFS I/O during the walk makes the Immich web UI
appear unresponsive — containers are healthy but VirtioFS is saturated by `readdir` calls.

**Potential causes:**
- Google Takeout archives contain thousands of small directories (one per album), each
  requiring a separate `readdir` call through VirtioFS → NFS → NAS
- VirtioFS does not cache directory listings aggressively; each `os.walk()` re-enumerates
  from the NAS even if the directory was recently scanned
- `UseResourceSaver:true` may throttle VM I/O during the walk, further slowing it

**To mitigate:** The walk cannot be avoided entirely, but its impact can be reduced:
- Run the importer when the Immich UI is not in active use
- Disable `UseResourceSaver` in Docker Desktop settings during import runs
- Consider pre-caching the file list to disk so subsequent runs skip the walk entirely

---

## 6. NFS server not responding — NAS at 192.168.1.253 went unresponsive mid-upload

**Occurrences:** 2 (2026-03-15 ~21:12 — 10 simultaneous failures; 2026-03-15 ~21:43 — 5 simultaneous failures triggered by NAS sync-write setting change)

**What happens:** The NFS server (`192.168.1.253:/volume/...`) stopped responding while
uploads were in progress. Because Immich's upload location (`/Volumes/nas/immich`) and
the photo source (`/Volumes/nas/Google Photos`) both mount from the same NFS server,
a single NFS outage simultaneously breaks both the file reads in the importer and any
Immich server-side writes. All 10 in-flight connections failed at once within a 6-second
window. The `ThreadPoolExecutor` then hung waiting on futures blocked on NFS I/O, making
the importer appear frozen with no further log output.

**Potential causes:**
- NAS (UniFi Drive at 192.168.1.253) overloaded by concurrent reads from the importer
  (10 parallel threads each reading a photo file over NFS simultaneously)
- NAS went to sleep or had a transient fault
- Network instability between the Mac and the NAS

**Symptoms:**
- Kernel logs show repeated `nfs server 192.168.1.253: not responding`
- All in-flight uploads fail simultaneously (burst of connection failures within seconds)
- Importer process hangs — no further log output, process still alive but blocked

**To recover:**
1. Wait for NFS to recover: `ls /Volumes/nas/` — if it hangs, the NAS is still down
2. Kill the hung importer: `kill 83132`
3. Restart once NAS is reachable — checkpoint resumes from where it left off:
```
python3 output/import.py --all
```
**To prevent:** Reduce `IMMICH_PARALLEL` to lower concurrent NFS reads, or stagger
uploads to avoid saturating the NAS I/O queue.

---

## 5. Stale file cache — test suite wrote temp paths into production `filelist.cache`

**Occurrences:** 2 (both at `2026-03-15T21:04–21:05Z`)

**What happens:** `filelist.cache` contained paths like
`/var/folders/.../tmpqyw90yo2/photo.jpg` — temp files created by pytest that no longer
exist. The importer read these from the cache and attempted to sha1-hash and upload them,
producing a cascade of three failures per stale entry:
1. `sha1 failed ... No such file or directory` — prechecker can't hash the file
2. `bulk-upload-check failed (HTTP Error 500)` — Immich returns 500 when the checksum batch contains a bad entry
3. `read failed ... No such file or directory` — upload can't open the file; logged as FAILED in checkpoint

**Root cause:** The `test_operational_log_written` test called `run_import()` without
patching `FILE_CACHE`, so `build_file_cache()` walked the test's temp `PHOTOS_DIR` and
overwrote the production cache with ephemeral paths.

**To recover:** Rebuild the cache from the real NAS:
```
python3 output/import.py --all --refresh-cache
```

**Fix applied:** `test_operational_log_written` now patches `FILE_CACHE` to an isolated
temp path so test runs never touch the production cache.

---

## 7. Prechecker silent for 9 minutes — SHA1-hashing 150,886 files over NFS with no log output

**Occurrences:** 1 (2026-03-15 21:34:21–21:43:23)

**What happens:** After "Using file cache", the prechecker reads all photo paths from the
local cache (instant) and immediately begins SHA1-hashing them over NFS in batches of 50,
using 6 concurrent SHA1 readers per batch. Because all upload futures are submitted before
`as_completed()` begins and progress lines only fire inside `as_completed()`, the operational
log shows no output at all for the entire 9-minute prechecker phase. The importer appears
frozen but is active (CPU ~20%).

**Potential causes:**
- Cache delivers all 150,886 paths instantly (no walk throttle), so prechecker runs at
  full speed — ~3,018 batches × 6 concurrent NFS reads each
- Progress logging is wired to the upload result loop, not to the prechecker phase
- Old behaviour: `os.walk()` over VirtioFS was slow enough to naturally throttle the
  prechecker; the cache removed that throttle

**Fix applied:** Prechecker now logs `INFO` at the start of each batch (`Prechecker: batch N
(50 files, hashing over NFS...)`) and `DEBUG` on completion. SHA1 pool reduced from 6 → 2
workers to lower concurrent NFS read pressure.

---

## 8. NAS sync-write setting change caused mid-run service interruption

**Occurrences:** 1 (2026-03-15 ~21:43)

**What happens:** Changing the NAS write-sync setting while the importer was actively uploading
caused a brief NFS service interruption. All 5 in-flight upload connections failed simultaneously
within a 4-second window (`21:43:23–27`). The importer process then exited without writing any
checkpoint entries (no CREATED/FAILED lines), losing the run entirely. Docker crashed again as
a result.

**Potential causes:**
- NAS service briefly restarts or flushes I/O queues when write-sync mode is toggled
- All parallel upload threads hit the outage simultaneously

**To prevent:** Avoid changing NAS settings while an import run is in progress.
