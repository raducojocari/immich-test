"""
tests/test_repair.py — pytest tests for output/repair.py

Run with: python3 -m pytest tests/test_repair.py -v
No live Immich server required — all external calls are mocked.
"""

import importlib.util
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Import the module under test (output/repair.py)
# ---------------------------------------------------------------------------
REPO_ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(REPO_ROOT, "output")

_spec = importlib.util.spec_from_file_location(
    "immich_repair", os.path.join(OUTPUT_DIR, "repair.py")
)
r = importlib.util.module_from_spec(_spec)
sys.modules["immich_repair"] = r
_spec.loader.exec_module(r)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mock_response(status, body):
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = json.dumps(body).encode()
    return mock_resp


# ---------------------------------------------------------------------------
# TestRepair
# ---------------------------------------------------------------------------
class TestRepair(unittest.TestCase):

    def test_query_all_assets_paginates(self):
        """GET /api/assets called in pages until empty page → returns all combined."""
        page1 = [{"id": "a1", "thumbhash": "abc", "deviceAssetId": "img1.jpg"}]
        page2 = [{"id": "a2", "thumbhash": None,  "deviceAssetId": "img2.jpg"}]
        page3 = []

        mock_conn = MagicMock()
        mock_conn.getresponse.side_effect = [
            _mock_response(200, page1),
            _mock_response(200, page2),
            _mock_response(200, page3),
        ]

        with patch.object(r, "get_conn", return_value=mock_conn):
            with patch.dict(os.environ, {"IMMICH_API_KEY": "testkey"}):
                result = r.query_all_assets()

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], "a1")
        self.assertEqual(result[1]["id"], "a2")

    def test_query_all_assets_http_error(self):
        """Non-200 response → returns [] and logs error."""
        mock_conn = MagicMock()
        mock_conn.getresponse.return_value = _mock_response(500, {"error": "server error"})

        with patch.object(r, "get_conn", return_value=mock_conn):
            with patch.dict(os.environ, {"IMMICH_API_KEY": "testkey"}):
                result = r.query_all_assets()

        self.assertEqual(result, [])

    def test_trigger_asset_jobs_sends_correct_body(self):
        """POST /api/assets/jobs body = {"assetIds": [...], "name": job_name}."""
        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_resp.read.return_value = b""
        mock_conn = MagicMock()
        mock_conn.getresponse.return_value = mock_resp

        with patch.object(r, "get_conn", return_value=mock_conn):
            with patch.dict(os.environ, {"IMMICH_API_KEY": "testkey"}):
                result = r.trigger_asset_jobs(["id1", "id2"], "regenerate-thumbnail")

        self.assertTrue(result)
        call_args = mock_conn.request.call_args
        sent_body = json.loads(call_args[1]["body"].decode())
        self.assertEqual(sent_body["assetIds"], ["id1", "id2"])
        self.assertEqual(sent_body["name"], "regenerate-thumbnail")

    def test_run_repair_no_broken_assets_returns_true(self):
        """All assets have thumbhash → no jobs triggered, returns True."""
        assets = [
            {"id": "a1", "thumbhash": "abc", "deviceAssetId": "img1.jpg"},
            {"id": "a2", "thumbhash": "def", "deviceAssetId": "img2.jpg"},
        ]

        with patch.object(r, "query_all_assets", return_value=assets):
            with patch.object(r, "trigger_asset_jobs") as mock_jobs:
                result = r.run_repair()

        self.assertTrue(result)
        mock_jobs.assert_not_called()

    def test_run_repair_triggers_both_jobs_for_broken(self):
        """Assets with thumbhash=null → trigger_asset_jobs called for both jobs."""
        assets = [
            {"id": "a1", "thumbhash": "abc", "deviceAssetId": "img1.jpg"},
            {"id": "a2", "thumbhash": None,  "deviceAssetId": "img2.jpg"},
            {"id": "a3", "thumbhash": None,  "deviceAssetId": "img3.jpg"},
        ]

        with patch.object(r, "query_all_assets", return_value=assets):
            with patch.object(r, "trigger_asset_jobs", return_value=True) as mock_jobs:
                result = r.run_repair()

        self.assertTrue(result)
        calls = mock_jobs.call_args_list
        self.assertEqual(len(calls), 2)
        ids_arg = calls[0][0][0]
        self.assertIn("a2", ids_arg)
        self.assertIn("a3", ids_arg)
        self.assertNotIn("a1", ids_arg)
        job_names = {c[0][1] for c in calls}
        self.assertIn("regenerate-thumbnail", job_names)
        self.assertIn("refresh-metadata", job_names)


if __name__ == "__main__":
    unittest.main()
