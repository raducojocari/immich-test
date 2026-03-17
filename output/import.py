#!/usr/bin/env python3
# import.py - Imports Google Photos Takeout archives into Immich.
#
# Usage:
#   IMMICH_API_KEY=<key> python3 output/import.py --test              # 5 sample photos
#   IMMICH_API_KEY=<key> python3 output/import.py --all               # all photos
#   IMMICH_API_KEY=<key> python3 output/import.py --all --withvideo   # all videos only
#   IMMICH_API_KEY=<key> python3 output/import.py --test --withvideo  # 5 sample videos
#
# The script is safe to re-run — files already in the log are skipped without
# touching the NAS, so it resumes cleanly after a crash or interruption.
#
# Tuning (set as env vars):
#   IMMICH_PARALLEL=10          concurrent photo uploads (default: 10)
#   IMMICH_VIDEO_PARALLEL=2     concurrent video uploads (default: 2)
#   IMMICH_TEST_COUNT=5         files for --test mode (default: 5)
#   IMMICH_LARGE_MB=99          files larger than this are skipped (default: 99)
#   NAS_MOUNT_POINT=/Volumes/nas      NFS mount point (default: /Volumes/nas)
#   NAS_REMOTE=192.168.1.1:/export    NFS remote — enables auto-remount on HTTP 000

import os
import sys
import json
import datetime
import threading
import time
import re
import signal
import logging
import pathlib
import itertools
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED, ALL_COMPLETED
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
LARGE_FILE_MB   = int(os.environ.get("IMMICH_LARGE_MB", "99"))
PROGRESS_INTERVAL = 50
NAS_MOUNT_POINT = os.environ.get("NAS_MOUNT_POINT", "/Volumes/nas")
NAS_REMOTE      = os.environ.get("NAS_REMOTE", "")   # e.g. "192.168.1.100:/volume1/photos"
DOCKER_COMPOSE_FILE = os.path.join(SCRIPT_DIR, "install", "docker-compose.yml")

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

# NAS remount state
_http000_count = 0
_http000_lock = threading.Lock()
HTTP000_REMOUNT_THRESHOLD = 10

# Recovery event — set by upload() when threshold is hit; cleared by run_import() on each loop
_recovery_event = threading.Event()


def _maybe_trigger_recovery():
    """Increment the shared failure counter; trigger recovery if threshold reached."""
    global _http000_count
    with _http000_lock:
        _http000_count += 1
        count = _http000_count
        if count >= HTTP000_REMOUNT_THRESHOLD:
            _http000_count = 0
    if count >= HTTP000_REMOUNT_THRESHOLD:
        logger.warning(
            "Failure threshold reached (%d) — triggering full recovery",
            HTTP000_REMOUNT_THRESHOLD,
        )
        _recovery_event.set()


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


def check_nas_reachable():
    if not os.path.isdir(PHOTOS_DIR):
        logger.error(
            "NAS no longer reachable at '%s' — triggering full recovery", PHOTOS_DIR
        )
        _recovery_event.set()


def full_recovery():
    """Stop uploads, remount NAS, restart Docker, wait for Immich. Called from main loop."""
    logger.warning("=== FULL RECOVERY START: remounting NAS + restarting Docker ===")

    # 1. Remount NAS
    mount_script = os.path.join(SCRIPT_DIR, "mount.sh")
    nas_mounted = os.path.ismount(NAS_MOUNT_POINT)
    if not nas_mounted:
        if os.path.isfile(mount_script):
            logger.warning("NAS not mounted — running sudo mount.sh: %s", mount_script)
            result = subprocess.run(
                ["sudo", mount_script],
                check=False, timeout=60, capture_output=True, text=True, stdin=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                logger.info("NAS remounted via mount.sh: %s", result.stdout.strip())
            else:
                logger.error("mount.sh failed (rc=%d): %s", result.returncode,
                             result.stderr.strip())
        elif NAS_REMOTE:
            logger.warning("Unmounting NAS: %s", NAS_MOUNT_POINT)
            subprocess.run(["sudo", "umount", "-f", NAS_MOUNT_POINT],
                           check=False, timeout=30, capture_output=True, stdin=subprocess.DEVNULL)
            time.sleep(2)
            subprocess.run(["sudo", "mkdir", "-p", NAS_MOUNT_POINT],
                           check=False, timeout=10, stdin=subprocess.DEVNULL)
            result = subprocess.run(
                ["sudo", "mount_nfs", "-o", "resvport", NAS_REMOTE, NAS_MOUNT_POINT],
                check=False, timeout=30, capture_output=True, text=True, stdin=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                logger.info("NAS remounted successfully.")
            else:
                logger.error("NAS remount failed (rc=%d): %s", result.returncode,
                             result.stderr.strip())
        else:
            logger.warning("NAS not mounted, mount.sh not found, and NAS_REMOTE not set "
                           "— Docker restart will likely fail")
    else:
        logger.info("NAS still mounted at %s — skipping remount", NAS_MOUNT_POINT)

    # 2. Restart Docker containers
    logger.warning("Restarting Docker containers: %s", DOCKER_COMPOSE_FILE)
    result = subprocess.run(
        ["docker", "compose", "-f", DOCKER_COMPOSE_FILE, "restart"],
        check=False, timeout=120, capture_output=True, text=True,
    )
    if result.returncode == 0:
        logger.info("Docker containers restarted.")
    else:
        logger.error("Docker restart failed (rc=%d): %s", result.returncode, result.stderr.strip())

    # 3. Wait for Immich to be healthy
    logger.info("Waiting for Immich to become healthy...")
    check_immich_reachable()  # retries 12×5s with logging

    logger.warning("=== FULL RECOVERY COMPLETE — resuming import ===")


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


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------
def find_media_files(extensions=MEDIA_EXTENSIONS):
    """Generator yielding absolute paths to media files filtered by extensions.
    Skips files >= LARGE_FILE_MB. Walks PHOTOS_DIR on every call."""
    large_bytes = LARGE_FILE_MB * 1024 * 1024
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
                if os.path.getsize(full) >= large_bytes:
                    logger.warning("Skipping large file (>%dMB): %s", LARGE_FILE_MB, full)
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


def get_conn() -> HTTPConnection:
    """Return a thread-local persistent HTTPConnection, creating one if needed."""
    parsed = urlparse(IMMICH_URL)
    host = parsed.hostname
    port = parsed.port or 80
    if not getattr(_local, "conn", None):
        _local.conn = HTTPConnection(host, port, timeout=60)
    return _local.conn


def upload(file_path: str) -> tuple:
    """Upload one file. Returns (status_str, relative_path)."""
    prefix = PHOTOS_DIR.rstrip("/") + "/"
    rel = file_path[len(prefix):] if file_path.startswith(prefix) else file_path

    if _recovery_event.is_set():
        return ("skipped:recovery", rel)
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
        body = build_multipart(fields, file_path, mime)
    except Exception as e:
        logger.warning("read failed %s: %s", rel, e)
        _maybe_trigger_recovery()
        return ("failed:read error", rel)

    ctype = "multipart/form-data; boundary=----immichboundary"
    api_key = os.environ.get("IMMICH_API_KEY", "")
    for attempt in range(3):
        try:
            conn = get_conn()
            conn.request(
                "POST", "/api/assets", body=body,
                headers={
                    "x-api-key": api_key,
                    "Content-Type": ctype,
                    "Accept": "application/json",
                    "Content-Length": str(len(body)),
                },
            )
            resp = conn.getresponse()
            code = resp.status
            rbody = resp.read().decode("utf-8", errors="replace")
            break
        except Exception:
            _local.conn = None
            if attempt == 2:
                _maybe_trigger_recovery()
                logger.warning("%s — connection failed after 3 attempts", rel)
                return ("failed:HTTP 000", rel)

    if code in (200, 201):
        try:
            status = json.loads(rbody).get("status", "created")
        except Exception:
            status = "created"
    else:
        logger.warning("%s — HTTP %d: %s", rel, code, rbody)
        if code == 500 and "Failed to upload asset" in rbody:
            _maybe_trigger_recovery()
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
    """Orchestrate the import. Returns True if no failures. Loops on recovery."""
    global _http000_count

    extensions = VIDEO_EXTENSIONS if with_video else PHOTO_EXTENSIONS
    media_type = "video" if with_video else "photo"
    workers = VIDEO_PARALLEL if with_video else MAX_PARALLEL
    prefix = PHOTOS_DIR.rstrip("/") + "/"
    start_time = int(time.time())

    log_checkpoint(f"=== Import started (mode={mode}, media={media_type}, parallel={workers}) ===")

    total_created = total_dupes = total_failed = total_processed = 0

    while True:
        _recovery_event.clear()
        with _http000_lock:
            _http000_count = 0

        checkpoint = load_checkpoint()
        skipped = len(checkpoint)

        created = dupes = failed = processed = 0

        if mode == "test":
            logger.info("Test mode: uploading first %d %s files...", TEST_COUNT, media_type)
        else:
            logger.info(
                "Full import | media=%s | %d parallel uploads | skipping files >%dMB | progress every %d files",
                media_type, workers, LARGE_FILE_MB, PROGRESS_INTERVAL,
            )

        # Build file source
        all_files = find_media_files(extensions)

        if mode == "test":
            source = itertools.islice(all_files, TEST_COUNT)
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
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for fut in done:
                    status, rel = fut.result()
                    if status == "skipped:recovery":
                        continue   # don't count, don't checkpoint

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
                        check_nas_reachable()
                        print_progress(processed, created, dupes, failed, start_time)

                if _recovery_event.is_set():
                    # Drain remaining futures (they'll return skipped:recovery)
                    for f in pending:
                        f.cancel()
                    if pending:
                        wait(pending, return_when=ALL_COMPLETED)
                    break   # exit while-pending loop

                try:
                    pending.add(pool.submit(upload, next(path_iter)))
                except StopIteration:
                    pass

        total_created += created
        total_dupes += dupes
        total_failed += failed
        total_processed += processed

        if _recovery_event.is_set():
            full_recovery()
            logger.info("Resuming import from checkpoint...")
            continue   # loop back: reload checkpoint, restart thread pool

        # Normal completion
        elapsed = int(time.time()) - start_time

        logger.info("")
        logger.info("=== Import complete ===")
        logger.info("  Imported  : %d", total_created)
        logger.info("  Duplicates: %d", total_dupes)
        logger.info("  Skipped   : %d (already processed in a prior run)", skipped)
        logger.info("  Failed    : %d", total_failed)
        logger.info("  Processed : %d", total_processed)
        logger.info("  Elapsed   : %s", format_duration(elapsed))
        logger.info("  Log       : %s", LOG_FILE)

        log_checkpoint(
            f"=== Import finished: created={total_created} duplicate={total_dupes} "
            f"skipped={skipped} failed={total_failed} elapsed={elapsed}s ==="
        )

        return total_failed == 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def usage():
    print(f"Usage: IMMICH_API_KEY=<key> python3 {sys.argv[0]} [--test|--all] [--withvideo]")
    print("")
    print(f"  --test                Upload {TEST_COUNT} sample photos (default)")
    print("  --all                 Upload all photos")
    print("  --all --withvideo     Upload all videos only")
    print("  --test --withvideo    Upload first 5 sample videos")
    print("")
    print(f"  IMMICH_PARALLEL={MAX_PARALLEL}          concurrent photo uploads (default: 10)")
    print(f"  IMMICH_VIDEO_PARALLEL={VIDEO_PARALLEL}    concurrent video uploads (default: 2)")
    sys.exit(1)


def main():
    setup_logging()

    args = set(sys.argv[1:])
    unknown = args - {"--test", "--all", "--withvideo"}
    if unknown:
        logger.error("Unknown flag: %s", next(iter(unknown)))
        usage()
    mode = "all" if "--all" in args else "test"
    with_video = "--withvideo" in args

    logger.info("=== Immich Importer ===")
    check_prerequisites()
    check_immich_reachable()
    success = run_import(mode, with_video)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
