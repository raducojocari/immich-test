"""
tests/test_import.py — pytest tests for output/import.py

Run with: python3 -m pytest tests/test_import.py -v
No live Immich server required — all external calls are mocked.
"""

import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch, mock_open, call

# ---------------------------------------------------------------------------
# Import the module under test (output/import.py)
# ---------------------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(REPO_ROOT, "output")

if OUTPUT_DIR not in sys.path:
    sys.path.insert(0, OUTPUT_DIR)

# The module file is named import.py which is a Python keyword — load it manually.
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "immich_import", os.path.join(OUTPUT_DIR, "import.py")
)
m = importlib.util.module_from_spec(_spec)
# Prevent the module-level code from running at import time
sys.modules["immich_import"] = m
_spec.loader.exec_module(m)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_log(lines):
    """Return a string simulating the content of import.log."""
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 1. Prerequisites
# ---------------------------------------------------------------------------
class TestPrerequisites(unittest.TestCase):

    def test_missing_api_key(self):
        """IMMICH_API_KEY="" → SystemExit(1)."""
        env = {k: v for k, v in os.environ.items() if k != "IMMICH_API_KEY"}
        env["IMMICH_API_KEY"] = ""
        with patch.dict(os.environ, env, clear=True):
            with patch.object(m, "PHOTOS_DIR", "/tmp"):
                with self.assertRaises(SystemExit) as ctx:
                    m.check_prerequisites()
        self.assertEqual(ctx.exception.code, 1)

    def test_missing_photos_dir(self):
        """IMMICH_PHOTOS_DIR=/nonexistent → SystemExit(1)."""
        with patch.dict(os.environ, {"IMMICH_API_KEY": "testkey"}):
            with patch.object(m, "PHOTOS_DIR", "/nonexistent_dir_xyz"):
                with self.assertRaises(SystemExit) as ctx:
                    m.check_prerequisites()
        self.assertEqual(ctx.exception.code, 1)

    def test_unknown_flag(self):
        """Unknown CLI flag → SystemExit(1)."""
        with patch.object(sys, "argv", ["import.py", "--bogus"]):
            with patch.object(m, "setup_logging"):
                with patch.object(m, "check_prerequisites"):
                    with patch.object(m, "check_immich_reachable"):
                        with self.assertRaises(SystemExit) as ctx:
                            m.main()
        self.assertEqual(ctx.exception.code, 1)

    def test_withvideo_flag_recognized(self):
        """--all --withvideo is a valid combination — no 'Unknown flag' error."""
        with patch.object(sys, "argv", ["import.py", "--all", "--withvideo"]):
            with patch.object(m, "setup_logging"):
                with patch.object(m, "check_prerequisites"):
                    with patch.object(m, "check_immich_reachable"):
                        with patch.object(m, "run_import", return_value=True):
                            try:
                                m.main()
                            except SystemExit as e:
                                self.assertEqual(e.code, 0)


# ---------------------------------------------------------------------------
# 2. Checkpoint
# ---------------------------------------------------------------------------
class TestCheckpoint(unittest.TestCase):

    def test_load_checkpoint_empty(self):
        """No import.log → returns empty set."""
        with tempfile.TemporaryDirectory() as td:
            with patch.object(m, "LOG_FILE", os.path.join(td, "import.log")):
                result = m.load_checkpoint()
        self.assertEqual(result, set())

    def test_load_checkpoint_reads_created_and_duplicate(self):
        """CREATED and DUPLICATE lines → included in checkpoint set."""
        lines = [
            "2026-03-14T10:00:00Z CREATED   Photos/2020/img1.jpg",
            "2026-03-14T10:00:01Z DUPLICATE Photos/2020/img2.jpg",
            "2026-03-14T10:00:02Z === Import started (mode=all, parallel=14) ===",
        ]
        content = _make_log(lines)
        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "import.log")
            with open(log_path, "w") as f:
                f.write(content)
            with patch.object(m, "LOG_FILE", log_path):
                result = m.load_checkpoint()
        self.assertIn("Photos/2020/img1.jpg", result)
        self.assertIn("Photos/2020/img2.jpg", result)
        self.assertEqual(len(result), 2)

    def test_load_checkpoint_ignores_failed(self):
        """FAILED lines → NOT included in checkpoint set."""
        lines = [
            "2026-03-14T10:00:00Z FAILED    Photos/2020/bad.jpg — HTTP 500",
        ]
        content = _make_log(lines)
        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "import.log")
            with open(log_path, "w") as f:
                f.write(content)
            with patch.object(m, "LOG_FILE", log_path):
                result = m.load_checkpoint()
        self.assertEqual(result, set())


# ---------------------------------------------------------------------------
# 3. File discovery
# ---------------------------------------------------------------------------
class TestFindMediaFiles(unittest.TestCase):

    def _find(self, photos_dir, extensions=None, large_mb=99):
        """Helper: run find_media_files with patched PHOTOS_DIR and LARGE_FILE_MB."""
        with patch.object(m, "PHOTOS_DIR", photos_dir):
            with patch.object(m, "LARGE_FILE_MB", large_mb):
                if extensions is not None:
                    return list(m.find_media_files(extensions))
                return list(m.find_media_files())

    def test_find_media_files_filters_by_extension(self):
        """Only media extensions are yielded; .txt is excluded."""
        with tempfile.TemporaryDirectory() as td:
            jpg = os.path.join(td, "photo.jpg")
            txt = os.path.join(td, "notes.txt")
            open(jpg, "w").close()
            open(txt, "w").close()
            results = self._find(td)
        self.assertIn(jpg, results)
        self.assertNotIn(txt, results)

    def test_find_media_files_photos_only(self):
        """Passing PHOTO_EXTENSIONS → jpg returned, mp4 not."""
        with tempfile.TemporaryDirectory() as td:
            jpg = os.path.join(td, "photo.jpg")
            mp4 = os.path.join(td, "clip.mp4")
            open(jpg, "w").close()
            open(mp4, "w").close()
            results = self._find(td, extensions=m.PHOTO_EXTENSIONS)
        self.assertIn(jpg, results)
        self.assertNotIn(mp4, results)

    def test_find_media_files_videos_only(self):
        """Passing VIDEO_EXTENSIONS → mp4 returned, jpg not."""
        with tempfile.TemporaryDirectory() as td:
            jpg = os.path.join(td, "photo.jpg")
            mp4 = os.path.join(td, "clip.mp4")
            open(jpg, "w").close()
            open(mp4, "w").close()
            results = self._find(td, extensions=m.VIDEO_EXTENSIONS)
        self.assertNotIn(jpg, results)
        self.assertIn(mp4, results)

    def test_find_media_files_skips_large_files(self):
        """Files >= LARGE_FILE_MB are not yielded."""
        with tempfile.TemporaryDirectory() as td:
            small = os.path.join(td, "small.jpg")
            large = os.path.join(td, "large.jpg")
            open(small, "w").close()
            with open(large, "wb") as f:
                f.write(b"\x00" * (2 * 1024 * 1024))  # 2 MB
            results = self._find(td, large_mb=1)
        self.assertIn(small, results)
        self.assertNotIn(large, results)


# ---------------------------------------------------------------------------
# 4. Upload mechanics
# ---------------------------------------------------------------------------
class TestGetMimeType(unittest.TestCase):

    def test_get_mime_type(self):
        cases = [
            ("photo.jpg", "image/jpeg"),
            ("photo.JPG", "image/jpeg"),
            ("clip.mp4", "video/mp4"),
            ("movie.mov", "video/quicktime"),
            ("image.heic", "image/heic"),
            ("data.bin", "application/octet-stream"),
        ]
        for filename, expected in cases:
            with self.subTest(filename=filename):
                self.assertEqual(m.get_mime_type(filename), expected)


class TestGetTakenAt(unittest.TestCase):

    def test_get_taken_at_from_sidecar(self):
        """JSON sidecar with photoTakenTime → correct ISO timestamp."""
        with tempfile.TemporaryDirectory() as td:
            img = os.path.join(td, "img.jpg")
            sidecar = img + ".json"
            open(img, "w").close()
            sidecar_data = {
                "photoTakenTime": {"timestamp": "1587300000", "formatted": "..."}
            }
            with open(sidecar, "w") as f:
                json.dump(sidecar_data, f)
            result = m.get_taken_at(img)
        # 1587300000 UTC = 2020-04-19T12:40:00Z
        self.assertEqual(result, "2020-04-19T12:40:00.000Z")

    def test_get_taken_at_fallback_mtime(self):
        """No sidecar → falls back to file mtime."""
        with tempfile.TemporaryDirectory() as td:
            img = os.path.join(td, "img.jpg")
            open(img, "w").close()
            result = m.get_taken_at(img)
        # Should be a valid ISO timestamp string
        self.assertRegex(result, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.000Z$")


class TestBuildMultipart(unittest.TestCase):

    def test_build_multipart_contains_fields(self):
        """Output bytes contain boundary, field names, and filename."""
        with tempfile.TemporaryDirectory() as td:
            img = os.path.join(td, "test.jpg")
            with open(img, "wb") as f:
                f.write(b"\xff\xd8\xff")  # minimal JPEG header
            fields = {
                "deviceAssetId": "rel/path/test.jpg",
                "deviceId": "import-script",
                "fileCreatedAt": "2020-04-19T16:20:00.000Z",
                "fileModifiedAt": "2020-04-19T16:20:00.000Z",
                "isFavorite": "false",
            }
            result = m.build_multipart(fields, img, "image/jpeg")
        self.assertIn(b"----immichboundary", result)
        self.assertIn(b"deviceAssetId", result)
        self.assertIn(b"test.jpg", result)
        self.assertIn(b"image/jpeg", result)
        self.assertIn(b"\xff\xd8\xff", result)


class TestUpload(unittest.TestCase):

    def _make_mock_conn(self, status, body_dict):
        mock_resp = MagicMock()
        mock_resp.status = status
        mock_resp.read.return_value = json.dumps(body_dict).encode()
        mock_conn = MagicMock()
        mock_conn.getresponse.return_value = mock_resp
        return mock_conn

    def _run_upload(self, mock_conn, img_path):
        with patch.object(m, "_local") as mock_local:
            mock_local.conn = mock_conn
            with patch.object(m, "get_conn", return_value=mock_conn):
                with patch.object(m, "get_taken_at", return_value="2020-01-01T00:00:00.000Z"):
                    with patch.dict(os.environ, {"IMMICH_API_KEY": "testkey"}):
                        with patch.object(m, "PHOTOS_DIR", os.path.dirname(img_path)):
                            return m.upload(img_path)

    def test_upload_created(self):
        """HTTP 201 + status=created → ('created', rel)."""
        with tempfile.TemporaryDirectory() as td:
            img = os.path.join(td, "photo.jpg")
            with open(img, "wb") as f:
                f.write(b"\x00" * 10)
            mock_conn = self._make_mock_conn(201, {"status": "created"})
            status, rel = self._run_upload(mock_conn, img)
        self.assertEqual(status, "created")
        self.assertEqual(rel, "photo.jpg")

    def test_upload_duplicate(self):
        """HTTP 200 + status=duplicate → ('duplicate', rel)."""
        with tempfile.TemporaryDirectory() as td:
            img = os.path.join(td, "photo.jpg")
            with open(img, "wb") as f:
                f.write(b"\x00" * 10)
            mock_conn = self._make_mock_conn(200, {"status": "duplicate"})
            status, rel = self._run_upload(mock_conn, img)
        self.assertEqual(status, "duplicate")

    def test_upload_http_500(self):
        """HTTP 500 → ('failed:HTTP 500', rel)."""
        with tempfile.TemporaryDirectory() as td:
            img = os.path.join(td, "photo.jpg")
            with open(img, "wb") as f:
                f.write(b"\x00" * 10)
            mock_conn = self._make_mock_conn(500, {"error": "server error"})
            status, rel = self._run_upload(mock_conn, img)
        self.assertEqual(status, "failed:HTTP 500")

    def test_upload_reconnects_on_connection_error(self):
        """First attempt raises ConnectionError; second succeeds → 'created'."""
        with tempfile.TemporaryDirectory() as td:
            img = os.path.join(td, "photo.jpg")
            with open(img, "wb") as f:
                f.write(b"\x00" * 10)

            call_count = {"n": 0}
            mock_resp = MagicMock()
            mock_resp.status = 201
            mock_resp.read.return_value = json.dumps({"status": "created"}).encode()

            mock_conn = MagicMock()

            def side_effect(*args, **kwargs):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise ConnectionError("connection reset")
                return None

            mock_conn.request.side_effect = side_effect
            mock_conn.getresponse.return_value = mock_resp

            # Reset _local.conn between attempts so get_conn() is called fresh
            with patch.object(m, "get_conn", return_value=mock_conn):
                with patch.object(m, "get_taken_at", return_value="2020-01-01T00:00:00.000Z"):
                    with patch.dict(os.environ, {"IMMICH_API_KEY": "testkey"}):
                        with patch.object(m, "PHOTOS_DIR", td):
                            status, rel = m.upload(img)

        self.assertEqual(status, "created")


# ---------------------------------------------------------------------------
# 5. Logging
# ---------------------------------------------------------------------------
class TestLogging(unittest.TestCase):

    def test_logs_dir_created_on_start(self):
        """setup_logging() creates logs/ dir and clears logs/import.log."""
        with tempfile.TemporaryDirectory() as td:
            script_dir = pathlib.Path(td)
            with patch.object(m, "SCRIPT_DIR", script_dir):
                # Remove any existing handlers to avoid pollution
                m.logger.handlers.clear()
                m.setup_logging()
                ops_log = script_dir / "logs" / "import.log"
                self.assertTrue(ops_log.parent.exists())
                self.assertTrue(ops_log.exists())
                # Clean up handlers
                m.logger.handlers.clear()

    def test_operational_log_written(self):
        """After run_import('test') with mocked upload, logs/import.log has content."""
        with tempfile.TemporaryDirectory() as td:
            # Create fake photos dir with one jpg
            photos_dir = os.path.join(td, "photos")
            os.makedirs(photos_dir)
            img = os.path.join(photos_dir, "test.jpg")
            with open(img, "wb") as f:
                f.write(b"\x00" * 10)

            script_dir_path = pathlib.Path(td)
            log_file = os.path.join(td, "import.log")

            with patch.object(m, "SCRIPT_DIR", script_dir_path):
                with patch.object(m, "LOG_FILE", log_file):
                    with patch.object(m, "PHOTOS_DIR", photos_dir):
                        with patch.object(m, "TEST_COUNT", 1):
                            with patch.object(
                                m, "upload",
                                return_value=("created", "test.jpg")
                            ):
                                m.logger.handlers.clear()
                                m.setup_logging()
                                m.run_import("test")
                                m.logger.handlers.clear()

            ops_log = script_dir_path / "logs" / "import.log"
            content = ops_log.read_text()
        self.assertTrue(len(content) > 0)


import pathlib  # needed for TestLogging


# ---------------------------------------------------------------------------
# 6. Single-pass import
# ---------------------------------------------------------------------------
class TestRunImportSinglePass(unittest.TestCase):

    def _make_photos_dir(self, td, count=3):
        photos_dir = os.path.join(td, "photos")
        os.makedirs(photos_dir)
        for i in range(count):
            with open(os.path.join(photos_dir, f"photo{i}.jpg"), "wb") as f:
                f.write(b"\x00" * 10)
        return photos_dir

    def test_clean_completion_returns_true(self):
        """run_import('all') with all uploads succeeding → returns True."""
        with tempfile.TemporaryDirectory() as td:
            photos_dir = self._make_photos_dir(td, count=3)
            log_file = os.path.join(td, "import.log")
            script_dir_path = pathlib.Path(td)

            with patch.object(m, "SCRIPT_DIR", script_dir_path):
                with patch.object(m, "LOG_FILE", log_file):
                    with patch.object(m, "PHOTOS_DIR", photos_dir):
                        with patch.object(m, "upload", return_value=("created", "photo.jpg")):
                            m.logger.handlers.clear()
                            m.setup_logging()
                            result = m.run_import("all")
                            m.logger.handlers.clear()

        self.assertTrue(result)

    def test_skips_checkpointed_files(self):
        """run_import('all') skips files already in the checkpoint log."""
        with tempfile.TemporaryDirectory() as td:
            photos_dir = self._make_photos_dir(td, count=3)
            log_file = os.path.join(td, "import.log")
            script_dir_path = pathlib.Path(td)

            # Pre-populate checkpoint with photo0.jpg and photo1.jpg
            with open(log_file, "w") as f:
                f.write("2026-03-14T10:00:00Z CREATED   photo0.jpg\n")
                f.write("2026-03-14T10:00:01Z CREATED   photo1.jpg\n")

            upload_calls = []

            def tracking_upload(path):
                upload_calls.append(os.path.basename(path))
                return ("created", os.path.basename(path))

            with patch.object(m, "SCRIPT_DIR", script_dir_path):
                with patch.object(m, "LOG_FILE", log_file):
                    with patch.object(m, "PHOTOS_DIR", photos_dir):
                        with patch.object(m, "upload", side_effect=tracking_upload):
                            m.logger.handlers.clear()
                            m.setup_logging()
                            m.run_import("all")
                            m.logger.handlers.clear()

        # Only photo2.jpg should be uploaded
        self.assertNotIn("photo0.jpg", upload_calls)
        self.assertNotIn("photo1.jpg", upload_calls)
        self.assertIn("photo2.jpg", upload_calls)

    def test_returns_false_on_failures(self):
        """run_import('test') with upload failures → returns False."""
        with tempfile.TemporaryDirectory() as td:
            photos_dir = self._make_photos_dir(td, count=1)
            log_file = os.path.join(td, "import.log")
            script_dir_path = pathlib.Path(td)

            with patch.object(m, "SCRIPT_DIR", script_dir_path):
                with patch.object(m, "LOG_FILE", log_file):
                    with patch.object(m, "PHOTOS_DIR", photos_dir):
                        with patch.object(m, "TEST_COUNT", 1):
                            with patch.object(
                                m, "upload", return_value=("failed:HTTP 500", "photo0.jpg")
                            ):
                                m.logger.handlers.clear()
                                m.setup_logging()
                                result = m.run_import("test")
                                m.logger.handlers.clear()

        self.assertFalse(result)


import time  # retained for any time-related assertions


# ---------------------------------------------------------------------------
# 7. Load failures
# ---------------------------------------------------------------------------
class TestLoadFailures(unittest.TestCase):

    def test_load_failures_empty(self):
        """No import.log → returns empty set."""
        with tempfile.TemporaryDirectory() as td:
            with patch.object(m, "LOG_FILE", os.path.join(td, "import.log")):
                result = m.load_failures()
        self.assertEqual(result, set())

    def test_load_failures_parses_failed_lines(self):
        """FAILED lines → included in failures set with path (not error detail)."""
        lines = [
            "2026-03-14T10:00:00Z FAILED    Photos/bad.jpg — HTTP 500",
            "2026-03-14T10:00:01Z FAILED    Photos/other.jpg — HTTP 000",
        ]
        content = _make_log(lines)
        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "import.log")
            with open(log_path, "w") as f:
                f.write(content)
            with patch.object(m, "LOG_FILE", log_path):
                result = m.load_failures()
        self.assertIn("Photos/bad.jpg", result)
        self.assertIn("Photos/other.jpg", result)
        self.assertEqual(len(result), 2)

    def test_load_failures_ignores_created_and_duplicate(self):
        """CREATED and DUPLICATE lines → NOT in failures set."""
        lines = [
            "2026-03-14T10:00:00Z CREATED   Photos/good.jpg",
            "2026-03-14T10:00:01Z DUPLICATE Photos/dupe.jpg",
            "2026-03-14T10:00:02Z FAILED    Photos/bad.jpg — HTTP 500",
        ]
        content = _make_log(lines)
        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "import.log")
            with open(log_path, "w") as f:
                f.write(content)
            with patch.object(m, "LOG_FILE", log_path):
                result = m.load_failures()
        self.assertNotIn("Photos/good.jpg", result)
        self.assertNotIn("Photos/dupe.jpg", result)
        self.assertIn("Photos/bad.jpg", result)
        self.assertEqual(len(result), 1)


# Extend TestRunImportSinglePass with failures-mode tests
class TestRunImportFailuresMode(unittest.TestCase):

    def _make_photos_dir(self, td, filenames):
        photos_dir = os.path.join(td, "photos")
        os.makedirs(photos_dir)
        for fname in filenames:
            with open(os.path.join(photos_dir, fname), "wb") as f:
                f.write(b"\x00" * 10)
        return photos_dir

    def test_failures_mode_retries_only_failed_files(self):
        """--failures mode: only files with FAILED entries are uploaded."""
        with tempfile.TemporaryDirectory() as td:
            photos_dir = self._make_photos_dir(td, ["good.jpg", "bad.jpg"])
            log_file = os.path.join(td, "import.log")
            script_dir_path = pathlib.Path(td)

            # Pre-populate log: good.jpg succeeded, bad.jpg failed
            with open(log_file, "w") as f:
                f.write("2026-03-14T10:00:00Z CREATED   good.jpg\n")
                f.write("2026-03-14T10:00:01Z FAILED    bad.jpg — HTTP 500\n")

            upload_calls = []

            def tracking_upload(path):
                name = os.path.basename(path)
                upload_calls.append(name)
                return ("created", name)

            with patch.object(m, "SCRIPT_DIR", script_dir_path):
                with patch.object(m, "LOG_FILE", log_file):
                    with patch.object(m, "PHOTOS_DIR", photos_dir):
                        with patch.object(m, "upload", side_effect=tracking_upload):
                            m.logger.handlers.clear()
                            m.setup_logging()
                            result = m.run_import("failures")
                            m.logger.handlers.clear()

        self.assertIn("bad.jpg", upload_calls)
        self.assertNotIn("good.jpg", upload_calls)
        self.assertTrue(result)

    def test_failures_mode_returns_true_when_no_failures(self):
        """--failures mode: no FAILED entries in log → returns True without uploads."""
        with tempfile.TemporaryDirectory() as td:
            photos_dir = self._make_photos_dir(td, ["photo.jpg"])
            log_file = os.path.join(td, "import.log")
            script_dir_path = pathlib.Path(td)

            # Log has only CREATED entries — no failures
            with open(log_file, "w") as f:
                f.write("2026-03-14T10:00:00Z CREATED   photo.jpg\n")

            upload_calls = []

            with patch.object(m, "SCRIPT_DIR", script_dir_path):
                with patch.object(m, "LOG_FILE", log_file):
                    with patch.object(m, "PHOTOS_DIR", photos_dir):
                        with patch.object(m, "upload", side_effect=lambda p: upload_calls.append(p) or ("created", p)):
                            m.logger.handlers.clear()
                            m.setup_logging()
                            result = m.run_import("failures")
                            m.logger.handlers.clear()

        self.assertEqual(upload_calls, [])
        self.assertTrue(result)


# ---------------------------------------------------------------------------
# 8. StreamingMultipart
# ---------------------------------------------------------------------------
class TestStreamingMultipart(unittest.TestCase):

    def _make_file(self, content: bytes):
        """Write content to a temp file and return its path (caller must unlink)."""
        fh = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        fh.write(content)
        fh.close()
        return fh.name

    def test_content_length_matches_actual_bytes(self):
        """content_length equals the number of bytes read() returns in total."""
        data = b"x" * 1024
        path = self._make_file(data)
        try:
            mp = m.StreamingMultipart(
                {"deviceAssetId": "test.mp4", "isFavorite": "false"},
                path, "video/mp4"
            )
            collected = b""
            while True:
                chunk = mp.read(256)
                if not chunk:
                    break
                collected += chunk
            self.assertEqual(len(collected), mp.content_length)
        finally:
            os.unlink(path)

    def test_streaming_produces_same_bytes_as_build_multipart(self):
        """StreamingMultipart output is byte-identical to build_multipart output."""
        data = b"video data here"
        path = self._make_file(data)
        try:
            fields = {"deviceAssetId": "test.mp4", "isFavorite": "false"}
            expected = m.build_multipart(fields, path, "video/mp4")
            mp = m.StreamingMultipart(fields, path, "video/mp4")
            actual = b""
            while True:
                chunk = mp.read(64)
                if not chunk:
                    break
                actual += chunk
            self.assertEqual(actual, expected)
        finally:
            os.unlink(path)

    def test_small_read_size_assembles_correctly(self):
        """Reading in 1-byte chunks still produces the full correct output."""
        data = b"abc"
        path = self._make_file(data)
        try:
            fields = {"deviceAssetId": "f.mp4", "isFavorite": "false"}
            expected = m.build_multipart(fields, path, "video/mp4")
            mp = m.StreamingMultipart(fields, path, "video/mp4")
            actual = b""
            while True:
                chunk = mp.read(1)
                if not chunk:
                    break
                actual += chunk
            self.assertEqual(actual, expected)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 9. compute_upload_timeout
# ---------------------------------------------------------------------------
class TestComputeUploadTimeout(unittest.TestCase):

    def test_small_file_returns_minimum_60(self):
        """Files under 1 MB → minimum timeout of 60 seconds (int(mb)=0, so 0+60=60)."""
        self.assertEqual(m.compute_upload_timeout(1024), 60)
        self.assertEqual(m.compute_upload_timeout(500 * 1024), 60)

    def test_large_file_scales_with_size(self):
        """1 GB file → timeout > 60 seconds."""
        one_gb = 1024 * 1024 * 1024
        self.assertGreater(m.compute_upload_timeout(one_gb), 60)
        self.assertEqual(m.compute_upload_timeout(one_gb), 1024 + 60)

    def test_timeout_formula(self):
        """Timeout = 1s per MB + 60s base."""
        mb_200 = 200 * 1024 * 1024
        self.assertEqual(m.compute_upload_timeout(mb_200), 200 + 60)


# ---------------------------------------------------------------------------
# 10. Video size cap (IMMICH_VIDEO_LARGE_MB)
# ---------------------------------------------------------------------------
class TestVideoSizeCap(unittest.TestCase):

    def test_video_mode_uses_video_cap(self):
        """In video mode, files > IMMICH_VIDEO_LARGE_MB are skipped."""
        with tempfile.TemporaryDirectory() as td:
            mp4 = os.path.join(td, "clip.mp4")
            with open(mp4, "wb") as f:
                f.write(b"\x00" * 10)
            with patch.object(m, "PHOTOS_DIR", td):
                with patch.object(m, "VIDEO_LARGE_FILE_MB", 1):
                    with patch("os.path.getsize", return_value=2 * 1024 * 1024):
                        results = list(m.find_media_files(m.VIDEO_EXTENSIONS, with_video=True))
            self.assertEqual(results, [])

    def test_video_mode_allows_files_under_video_cap(self):
        """In video mode, files < IMMICH_VIDEO_LARGE_MB are included."""
        with tempfile.TemporaryDirectory() as td:
            mp4 = os.path.join(td, "clip.mp4")
            with open(mp4, "wb") as f:
                f.write(b"\x00" * 10)
            with patch.object(m, "PHOTOS_DIR", td):
                with patch.object(m, "VIDEO_LARGE_FILE_MB", 100):
                    with patch("os.path.getsize", return_value=50 * 1024 * 1024):
                        results = list(m.find_media_files(m.VIDEO_EXTENSIONS, with_video=True))
            self.assertIn(mp4, results)

    def test_photo_mode_unaffected_by_video_cap(self):
        """Changing VIDEO_LARGE_FILE_MB has no effect on photo mode."""
        with tempfile.TemporaryDirectory() as td:
            jpg = os.path.join(td, "photo.jpg")
            with open(jpg, "wb") as f:
                f.write(b"\x00" * 10)
            with patch.object(m, "PHOTOS_DIR", td):
                with patch.object(m, "LARGE_FILE_MB", 99):
                    with patch.object(m, "VIDEO_LARGE_FILE_MB", 1):
                        with patch("os.path.getsize", return_value=50 * 1024 * 1024):
                            results = list(m.find_media_files(m.PHOTO_EXTENSIONS, with_video=False))
            self.assertIn(jpg, results)


# ---------------------------------------------------------------------------
# PID file
# ---------------------------------------------------------------------------
class TestPidFile(unittest.TestCase):

    def test_pid_file_written_and_removed_on_exit(self):
        """main() writes import.pid with the current PID and removes it via atexit."""
        import pathlib
        with tempfile.TemporaryDirectory() as td:
            pid_path = pathlib.Path(td) / "import.pid"
            with patch.object(m, "SCRIPT_DIR", pathlib.Path(td)), \
                 patch.object(m, "setup_logging"), \
                 patch.object(m, "check_prerequisites"), \
                 patch.object(m, "check_immich_reachable"), \
                 patch.object(m, "run_import", return_value=True), \
                 patch("sys.argv", ["import.py", "--all"]), \
                 patch("sys.exit"):
                m.main()
            # After main() returns, atexit has NOT been fired yet in this test —
            # just verify the file was written with the correct PID
            self.assertTrue(pid_path.exists(), "import.pid was not created")
            self.assertEqual(pid_path.read_text().strip(), str(os.getpid()))


if __name__ == "__main__":
    unittest.main()
