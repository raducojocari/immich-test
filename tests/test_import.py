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

    def test_find_media_files_filters_by_extension(self):
        """Only media extensions are yielded; .txt is excluded."""
        with tempfile.TemporaryDirectory() as td:
            jpg = os.path.join(td, "photo.jpg")
            txt = os.path.join(td, "notes.txt")
            open(jpg, "w").close()
            open(txt, "w").close()
            with patch.object(m, "PHOTOS_DIR", td):
                with patch.object(m, "LARGE_FILE_MB", 99):
                    results = list(m.find_media_files())
        self.assertIn(jpg, results)
        self.assertNotIn(txt, results)

    def test_find_media_files_skips_large_files(self):
        """Files >= LARGE_FILE_MB are not yielded."""
        with tempfile.TemporaryDirectory() as td:
            small = os.path.join(td, "small.jpg")
            large = os.path.join(td, "large.jpg")
            open(small, "w").close()
            # Write exactly 1 byte over the limit
            with open(large, "wb") as f:
                f.write(b"\x00" * (2 * 1024 * 1024))  # 2 MB
            with patch.object(m, "PHOTOS_DIR", td):
                with patch.object(m, "LARGE_FILE_MB", 1):  # 1 MB limit
                    results = list(m.find_media_files())
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
# 5. Prechecker
# ---------------------------------------------------------------------------
class TestPrechecker(unittest.TestCase):

    def test_prechecker_yields_new_files(self):
        """bulk_upload_check returns one reject → rejected path not yielded."""
        paths = ["/photos/new.jpg", "/photos/old.jpg"]
        # old.jpg is already in Immich (reject)
        mock_result = {"old.jpg"}

        with patch.object(m, "PHOTOS_DIR", "/photos"):
            with patch.object(m, "BATCH_SIZE", 50):
                with patch.object(m, "bulk_upload_check", return_value=mock_result):
                    dupes = []
                    result = list(m.prechecker(iter(paths), dupes))

        self.assertIn("/photos/new.jpg", result)
        self.assertNotIn("/photos/old.jpg", result)
        self.assertIn("old.jpg", dupes)

    def test_prechecker_batches_correctly(self):
        """120 paths with BATCH_SIZE=50 → 3 calls to bulk_upload_check."""
        paths = [f"/photos/file{i:03d}.jpg" for i in range(120)]

        call_count = {"n": 0}

        def mock_bulk(batch):
            call_count["n"] += 1
            return set()  # no duplicates

        with patch.object(m, "PHOTOS_DIR", "/photos"):
            with patch.object(m, "BATCH_SIZE", 50):
                with patch.object(m, "bulk_upload_check", side_effect=mock_bulk):
                    dupes = []
                    list(m.prechecker(iter(paths), dupes))

        self.assertEqual(call_count["n"], 3)


# ---------------------------------------------------------------------------
# 6. Logging
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
                            with patch.object(m, "check_nas_reachable"):
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


if __name__ == "__main__":
    unittest.main()
