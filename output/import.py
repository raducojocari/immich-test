#!/usr/bin/env python3
# import.py - Imports Google Photos Takeout archives into Immich.
#
# Usage:
#   IMMICH_API_KEY=<key> python3 output/import.py --test              # 5 sample photos
#   IMMICH_API_KEY=<key> python3 output/import.py --all               # all photos
#   IMMICH_API_KEY=<key> python3 output/import.py --all --withvideo   # all videos only
#   IMMICH_API_KEY=<key> python3 output/import.py --test --withvideo  # 5 sample videos
#   IMMICH_API_KEY=<key> python3 output/import.py --failures          # retry failed files
#
# The script is safe to re-run — files already in the log are skipped without
# touching the NAS, so it resumes cleanly after a crash or interruption.
#
# Tuning (set as env vars):
#   IMMICH_PARALLEL=10          concurrent photo uploads (default: 10)
#   IMMICH_VIDEO_PARALLEL=2     concurrent video uploads (default: 2)
#   IMMICH_TEST_COUNT=5         files for --test mode (default: 5)
#   IMMICH_LARGE_MB=99          photo files larger than this MB are skipped (default: 99)
#   IMMICH_VIDEO_LARGE_MB=4096  video files larger than this MB are skipped (default: 4096)
#   NAS_MOUNT_POINT=/Volumes/nas      NFS mount point (default: /Volumes/nas)

import atexit
import io
import os
import sys
import re
import json
import datetime
import threading
import time
import logging
import pathlib
import itertools
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from http.client import HTTPConnection
from urllib.request import Request, urlopen
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR = pathlib.Path(__file__).parent.resolve()

PHOTOS_DIR      = os.environ.get("IMMICH_PHOTOS_DIR", "/Volumes/nas/Google Photos/Radu")
IMMICH_URL      = os.environ.get("IMMICH_URL", "http://localhost:2283")
TEST_COUNT      = int(os.environ.get("IMMICH_TEST_COUNT", "5"))
LOG_FILE        = str(SCRIPT_DIR / "import.log")
MAX_PARALLEL    = int(os.environ.get("IMMICH_PARALLEL", "10"))
VIDEO_PARALLEL  = int(os.environ.get("IMMICH_VIDEO_PARALLEL", "2"))
LARGE_FILE_MB       = int(os.environ.get("IMMICH_LARGE_MB", "99"))
VIDEO_LARGE_FILE_MB = int(os.environ.get("IMMICH_VIDEO_LARGE_MB", "4096"))  # 4 GB default
PROGRESS_INTERVAL = 50
NAS_MOUNT_POINT = os.environ.get("NAS_MOUNT_POINT", "/Volumes/nas")

PHOTO_EXTENSIONS = {
    "jpg", "jpeg", "png", "gif", "heic", "heif", "tiff", "tif", "webp", "bmp",
}
VIDEO_EXTENSIONS = {
    "mp4", "mov", "avi", "mkv", "wmv", "m4v", "3gp",
}
MEDIA_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS   # retained for MIME_MAP completeness

MIME_MAP = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "heic": "image/heic", "heif": "image/heif",
    "tiff": "image/tiff", "tif": "image/tiff", "webp": "image/webp",
    "bmp": "image/bmp", "mp4": "video/mp4", "mov": "video/quicktime",
    "avi": "video/x-msvideo", "mkv": "video/x-matroska",
    "wmv": "video/x-ms-wmv", "m4v": "video/x-m4v", "3gp": "video/3gpp",
}

# Thread-local HTTP connection pool
_local = threading.local()

# Module-level logger (configured by setup_logging)
logger = logging.getLogger("immich_import")

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
def setup_logging():
    """Configure logging to stdout and logs/import.log (cleared on each start)."""
    logs_dir = SCRIPT_DIR / "logs"
    logs_dir.mkdir(exist_ok=True)
    ops_log = logs_dir / "import.log"
    # Clear operational log on each start (CLAUDE.md compliance)
    ops_log.write_text("")

    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("[%(levelname)s] %(message)s")

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.setFormatter(fmt)

    file_handler = logging.FileHandler(str(ops_log))
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    logger.addHandler(stdout_handler)
    logger.addHandler(file_handler)

    logger.debug("Logging initialised. Operational log: %s", ops_log)


def log_checkpoint(message: str):
    """Append a line to the persistent import.log checkpoint file."""
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(LOG_FILE, "a") as f:
        f.write(f"{ts} {message}\n")


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------
def check_prerequisites():
    logger.info("Checking prerequisites...")
    api_key = os.environ.get("IMMICH_API_KEY", "")
    if not api_key:
        logger.error(
            "IMMICH_API_KEY not set. Get one from: %s → Account Settings → API Keys",
            IMMICH_URL,
        )
        sys.exit(1)
    if not os.path.isdir(PHOTOS_DIR):
        logger.error("Photos directory not found: '%s'. Is the NAS mounted?", PHOTOS_DIR)
        sys.exit(1)
    logger.info("Prerequisites satisfied.")


def check_immich_reachable():
    """Ping Immich and validate the API key. Retries up to 12×5s."""
    logger.info("Checking Immich...")
    attempts = 12
    delay = 5
    for i in range(1, attempts + 1):
        try:
            req = Request(f"{IMMICH_URL}/api/server/ping", method="GET")
            with urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    break
                code = resp.status
        except Exception:
            code = 0
        if i == attempts:
            logger.error(
                "Cannot reach Immich at %s after %ds. Run ./start.sh first.",
                IMMICH_URL, attempts * delay,
            )
            sys.exit(1)
        logger.info("Immich not ready yet (HTTP %s), retrying in %ds... (%d/%d)", code, delay, i, attempts)
        time.sleep(delay)

    # Validate API key
    try:
        req = Request(
            f"{IMMICH_URL}/api/users/me",
            headers={"x-api-key": os.environ.get("IMMICH_API_KEY", "")},
        )
        with urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                raise ValueError(f"HTTP {resp.status}")
    except Exception:
        logger.error("API key invalid or expired. Generate a new one in the Immich web UI.")
        sys.exit(1)

    logger.info("Immich reachable. API key valid.")


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------
def load_checkpoint() -> set:
    """Parse import.log and return a set of relative paths already processed."""
    done = set()
    if not os.path.isfile(LOG_FILE):
        return done
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z (CREATED|DUPLICATE)\s+(.+)$")
    with open(LOG_FILE) as f:
        for line in f:
            m = pattern.match(line.rstrip("\n"))
            if m:
                done.add(m.group(2))
    if done:
        logger.info("Checkpoint: %d already processed — will skip.", len(done))
    return done


def load_failures() -> set:
    """Parse import.log and return a set of relative paths that previously failed."""
    failed = set()
    if not os.path.isfile(LOG_FILE):
        return failed
    pattern = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z FAILED\s+(.+?)\s+—\s+.+$"
    )
    with open(LOG_FILE) as f:
        for line in f:
            match = pattern.match(line.rstrip("\n"))
            if match:
                failed.add(match.group(1))
    if failed:
        logger.info("Found %d previously failed files to retry.", len(failed))
    return failed


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------
def find_media_files(extensions=MEDIA_EXTENSIONS, with_video: bool = False):
    """Generator yielding absolute paths to media files filtered by extensions.
    Skips files >= LARGE_FILE_MB (photos) or IMMICH_VIDEO_LARGE_MB (videos).
    Walks PHOTOS_DIR on every call."""
    cap_mb = VIDEO_LARGE_FILE_MB if with_video else LARGE_FILE_MB
    cap_bytes = cap_mb * 1024 * 1024
    logger.info("Walking NAS: %s", PHOTOS_DIR)
    dirs_visited = 0
    for root, _dirs, files in os.walk(PHOTOS_DIR):
        dirs_visited += 1
        if dirs_visited % 10 == 0:
            logger.info("Walking... %d dirs scanned so far", dirs_visited)
        for fname in files:
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
            if ext not in extensions:
                continue
            full = os.path.join(root, fname)
            try:
                if os.path.getsize(full) >= cap_bytes:
                    logger.warning("Skipping large file (>%dMB): %s", cap_mb, full)
                    continue
            except OSError:
                continue
            yield full


# ---------------------------------------------------------------------------
# Upload helpers
# ---------------------------------------------------------------------------
def get_mime_type(path: str) -> str:
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return MIME_MAP.get(ext, "application/octet-stream")


def get_taken_at(path: str) -> str:
    """Return ISO timestamp: from JSON sidecar photoTakenTime, or file mtime."""
    json_file = path + ".json"
    if os.path.isfile(json_file):
        try:
            with open(json_file) as f:
                d = json.load(f)
            ts = int(d.get("photoTakenTime", d.get("creationTime", {})).get("timestamp", 0))
            if ts:
                return datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        except Exception:
            pass
    mtime = os.stat(path).st_mtime
    return datetime.datetime.utcfromtimestamp(mtime).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# Retained as test oracle for StreamingMultipart byte-identity verification.
def build_multipart(fields: dict, file_path: str, mime: str) -> bytes:
    boundary = b"----immichboundary"
    body = b""
    for name, val in fields.items():
        body += b"--" + boundary + b"\r\n"
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode()
    fname = os.path.basename(file_path)
    body += b"--" + boundary + b"\r\n"
    body += (
        f'Content-Disposition: form-data; name="assetData"; filename="{fname}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode()
    with open(file_path, "rb") as fh:
        body += fh.read()
    body += b"\r\n--" + boundary + b"--\r\n"
    return body


class StreamingMultipart:
    """Streams multipart/form-data without loading the file into memory.

    Provides a read() interface accepted by http.client.HTTPConnection.request()
    and exposes content_length for the Content-Length header.
    Content-Length is computed from file metadata so no file I/O occurs at
    construction time.
    """

    BOUNDARY = b"----immichboundary"

    def __init__(self, fields: dict, file_path: str, mime: str):
        preamble = b""
        for name, val in fields.items():
            preamble += b"--" + self.BOUNDARY + b"\r\n"
            preamble += f'Content-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode()
        fname = os.path.basename(file_path)
        preamble += b"--" + self.BOUNDARY + b"\r\n"
        preamble += (
            f'Content-Disposition: form-data; name="assetData"; filename="{fname}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode()
        epilogue = b"\r\n--" + self.BOUNDARY + b"--\r\n"

        self._preamble = preamble
        self._epilogue = epilogue
        self._file_path = file_path
        self.content_length = len(preamble) + os.path.getsize(file_path) + len(epilogue)

        # Stream state — lazily initialised on first read()
        self._parts = None
        self._part_idx = 0

    def _init(self):
        self._parts = [
            io.BytesIO(self._preamble),
            open(self._file_path, "rb"),
            io.BytesIO(self._epilogue),
        ]

    def read(self, size: int = 65536) -> bytes:
        if self._parts is None:
            self._init()
        buf = b""
        while len(buf) < size and self._part_idx < len(self._parts):
            chunk = self._parts[self._part_idx].read(size - len(buf))
            if chunk:
                buf += chunk
            else:
                self._parts[self._part_idx].close()
                self._part_idx += 1
        return buf

    def close(self):
        """Close any open part handles (called on upload failure to prevent fd leaks)."""
        if self._parts:
            for part in self._parts[self._part_idx:]:
                try:
                    part.close()
                except Exception:
                    pass
            self._parts = None


def compute_upload_timeout(file_size_bytes: int) -> int:
    """Return a connection timeout in seconds: 1 second per MB + 60 second base.

    Assumes a conservative minimum throughput of 1 MB/s over local network.
    Minimum is 60 seconds.
    """
    mb = file_size_bytes / (1024 * 1024)
    return max(60, int(mb) + 60)


def get_conn(timeout: int = 60) -> HTTPConnection:
    """Return a thread-local persistent HTTPConnection, creating one if needed.
    Recreates the connection if the required timeout differs from the current one."""
    parsed = urlparse(IMMICH_URL)
    host = parsed.hostname
    port = parsed.port or 80
    if not getattr(_local, "conn", None) or getattr(_local, "conn_timeout", 60) != timeout:
        old = getattr(_local, "conn", None)
        if old:
            try:
                old.close()
            except Exception:
                pass
        _local.conn = HTTPConnection(host, port, timeout=timeout)
        _local.conn_timeout = timeout
    return _local.conn


def upload(file_path: str) -> tuple:
    """Upload one file using streaming multipart. Returns (status_str, relative_path)."""
    prefix = PHOTOS_DIR.rstrip("/") + "/"
    rel = file_path[len(prefix):] if file_path.startswith(prefix) else file_path

    mime = get_mime_type(file_path)
    try:
        taken_at = get_taken_at(file_path)
    except Exception:
        taken_at = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")

    fields = {
        "deviceAssetId": rel,
        "deviceId": "import-script",
        "fileCreatedAt": taken_at,
        "fileModifiedAt": taken_at,
        "isFavorite": "false",
    }

    try:
        file_size = os.path.getsize(file_path)
    except OSError as e:
        logger.warning("read failed %s: %s", rel, e)
        return ("failed:read error", rel)

    timeout = compute_upload_timeout(file_size)
    ctype = "multipart/form-data; boundary=" + StreamingMultipart.BOUNDARY.decode()
    api_key = os.environ.get("IMMICH_API_KEY", "")

    for attempt in range(3):
        mp = StreamingMultipart(fields, file_path, mime)
        try:
            conn = get_conn(timeout=timeout)
            conn.request(
                "POST", "/api/assets", body=mp,
                headers={
                    "x-api-key": api_key,
                    "Content-Type": ctype,
                    "Accept": "application/json",
                    "Content-Length": str(mp.content_length),
                },
            )
            resp = conn.getresponse()
            code = resp.status
            rbody = resp.read().decode("utf-8", errors="replace")
            break
        except Exception:
            mp.close()
            _local.conn = None
            if attempt == 2:
                logger.warning("%s — connection failed after 3 attempts", rel)
                return ("failed:HTTP 000", rel)

    if code in (200, 201):
        try:
            status = json.loads(rbody).get("status", "created")
        except Exception:
            status = "created"
    else:
        logger.warning("%s — HTTP %d: %s", rel, code, rbody)
        status = f"failed:HTTP {code}"
    return (status, rel)


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------
def format_duration(secs: int) -> str:
    return f"{secs // 3600:02d}:{(secs % 3600) // 60:02d}:{secs % 60:02d}"


def print_progress(processed, created, dupes, failed, start_time):
    elapsed = int(time.time()) - start_time
    rate = (processed * 60) // elapsed if elapsed > 0 else 0
    logger.info(
        "[PROGRESS] %d processed | %d imported | %d dupes | %d failed | %d files/min | elapsed: %s",
        processed, created, dupes, failed, rate, format_duration(elapsed),
    )


# ---------------------------------------------------------------------------
# Main import runner
# ---------------------------------------------------------------------------
def run_import(mode: str, with_video: bool = False) -> bool:
    """Single-pass import. Returns True if no failures."""
    extensions = VIDEO_EXTENSIONS if with_video else PHOTO_EXTENSIONS
    media_type = "video" if with_video else "photo"
    workers = VIDEO_PARALLEL if with_video else MAX_PARALLEL
    prefix = PHOTOS_DIR.rstrip("/") + "/"
    start_time = int(time.time())

    log_checkpoint(f"=== Import started (mode={mode}, media={media_type}, parallel={workers}) ===")

    checkpoint = load_checkpoint()
    skipped = len(checkpoint)

    created = dupes = failed = processed = 0

    file_size_cap_mb = VIDEO_LARGE_FILE_MB if with_video else LARGE_FILE_MB
    if mode == "test":
        logger.info("Test mode: uploading first %d %s files...", TEST_COUNT, media_type)
    else:
        logger.info(
            "Full import | media=%s | %d parallel uploads | skipping files >%dMB | progress every %d files",
            media_type, workers, file_size_cap_mb, PROGRESS_INTERVAL,
        )

    # Build file source
    all_files = find_media_files(extensions, with_video=with_video)

    if mode == "test":
        source = itertools.islice(all_files, TEST_COUNT)
    elif mode == "failures":
        failed_set = load_failures()
        if not failed_set:
            logger.info("No failed files in log — nothing to retry.")
            return True
        logger.info(
            "Retrying %d previously failed %s files...", len(failed_set), media_type
        )
        def failures_only():
            for p in all_files:
                rel = p[len(prefix):] if p.startswith(prefix) else p
                if rel in failed_set and rel not in checkpoint:
                    yield p
        source = failures_only()
    else:
        def filtered():
            for p in all_files:
                rel = p[len(prefix):] if p.startswith(prefix) else p
                if rel not in checkpoint:
                    yield p
        source = filtered()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        path_iter = iter(source)
        pending = set()
        for path in itertools.islice(path_iter, workers * 3):
            pending.add(pool.submit(upload, path))
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED, timeout=5)
            for fut in done:
                status, rel = fut.result()
                processed += 1
                if status == "created":
                    created += 1
                    logger.info("[OK]    (%d) %s", processed, rel)
                    log_checkpoint(f"CREATED   {rel}")
                elif status == "duplicate":
                    dupes += 1
                    logger.info("[SKIP]  (%d) %s", processed, rel)
                    log_checkpoint(f"DUPLICATE {rel}")
                else:
                    failed += 1
                    detail = status[len("failed:"):] if status.startswith("failed:") else status
                    logger.warning("[WARN]  (%d) %s — %s", processed, rel, detail)
                    log_checkpoint(f"FAILED    {rel} — {detail}")
                if processed % PROGRESS_INTERVAL == 0:
                    print_progress(processed, created, dupes, failed, start_time)
            try:
                pending.add(pool.submit(upload, next(path_iter)))
            except StopIteration:
                pass

    elapsed = int(time.time()) - start_time

    logger.info("")
    logger.info("=== Import complete ===")
    logger.info("  Imported  : %d", created)
    logger.info("  Duplicates: %d", dupes)
    logger.info("  Skipped   : %d (already processed in a prior run)", skipped)
    logger.info("  Failed    : %d", failed)
    logger.info("  Processed : %d", processed)
    logger.info("  Elapsed   : %s", format_duration(elapsed))
    logger.info("  Log       : %s", LOG_FILE)

    log_checkpoint(
        f"=== Import finished: created={created} duplicate={dupes} "
        f"skipped={skipped} failed={failed} elapsed={elapsed}s ==="
    )

    return failed == 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def usage():
    print(f"Usage: IMMICH_API_KEY=<key> python3 {sys.argv[0]} [--test|--all|--failures] [--withvideo]")
    print("")
    print(f"  --test                Upload {TEST_COUNT} sample photos (default)")
    print("  --all                 Upload all photos")
    print("  --failures            Retry only previously failed files")
    print("  --all --withvideo     Upload all videos only")
    print("  --test --withvideo    Upload first 5 sample videos")
    print("  --failures --withvideo  Retry failed video files only")
    print("")
    print(f"  IMMICH_PARALLEL={MAX_PARALLEL}          concurrent photo uploads (default: 10)")
    print(f"  IMMICH_VIDEO_PARALLEL={VIDEO_PARALLEL}    concurrent video uploads (default: 2)")
    sys.exit(1)


def main():
    setup_logging()

    # Write PID file so recover.sh can detect this process reliably on macOS
    pid_file = SCRIPT_DIR / "import.pid"
    pid_file.write_text(str(os.getpid()))
    atexit.register(lambda: pid_file.unlink(missing_ok=True))

    args = set(sys.argv[1:])
    unknown = args - {"--test", "--all", "--withvideo", "--failures"}
    if unknown:
        logger.error("Unknown flag: %s", next(iter(unknown)))
        usage()

    if "--failures" in args and ("--all" in args or "--test" in args):
        logger.error("--failures cannot be combined with --all or --test")
        usage()

    if "--failures" in args:
        mode = "failures"
    elif "--all" in args:
        mode = "all"
    else:
        mode = "test"
    with_video = "--withvideo" in args

    logger.info("=== Immich Importer ===")
    check_prerequisites()
    check_immich_reachable()
    success = run_import(mode, with_video)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
