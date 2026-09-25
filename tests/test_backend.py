"""Exercise real API handlers and background jobs without needing a listening port."""

import csv
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.jobs import JobError, JobStore
from backend.server import Handler
from video_pipeline import demo_frames


class Connection:
    """In-memory transport for BaseHTTPRequestHandler's real HTTP parser."""
    def __init__(self, data):
        self.reader = io.BytesIO(data)
        self.output = bytearray()
    def makefile(self, *args): return self.reader
    def settimeout(self, timeout): pass
    def sendall(self, data): self.output.extend(data)


class QuietHandler(Handler):
    def log_message(self, *args): pass


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = JobStore(Path(self.temp.name))
        self.addCleanup(self.store.close)

    def api(self, path, method="GET", data=None, headers=None, body=None):
        fields = {"Host": "127.0.0.1:8000", "X-VisionWeave-Request": "1"}
        if data is not None:
            body = json.dumps(data).encode()
            fields["Content-Type"] = "application/json"
        body = body or b""
        fields["Content-Length"] = str(len(body))
        fields.update(headers or {})
        wire = f"{method} {path} HTTP/1.0\r\n" + "".join(f"{k}: {v}\r\n" for k, v in fields.items()) + "\r\n"
        connection = Connection(wire.encode() + body)
        QuietHandler(connection, ("127.0.0.1", 9000), SimpleNamespace(store=self.store, server_port=8000))
        head, payload = bytes(connection.output).split(b"\r\n\r\n", 1)
        status = int(head.split(b" ", 2)[1])
        return status, payload, head

    def wait_done(self, job_id):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = self.store.get(job_id)
            if job["status"] in {"completed", "failed", "cancelled"}:
                return job
            time.sleep(.01)
        self.fail("Background job did not finish")

    def test_full_demo_request_status_preview_pagination_and_csv(self):
        status, body, _ = self.api("/api/jobs/demo", "POST", {"max_frames": 60})
        self.assertEqual(status, 202)
        job = self.wait_done(json.loads(body)["id"])
        self.assertEqual(job["status"], "completed", job["error"])
        self.assertEqual((job["frames"], job["rows"], job["boxes"], job["points"], job["empty"]), (60, 120, 50, 40, 30))
        route = f'/api/jobs/{job["id"]}'
        status, data, _ = self.api(route)
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(data)["previews"]), 60)
        status, jpeg, _ = self.api(route + "/frames/0.jpg")
        self.assertEqual(status, 200)
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))
        status, data, _ = self.api(route + "/results?offset=20&limit=20")
        self.assertEqual(status, 200)
        result = json.loads(data)
        self.assertEqual((len(result["rows"]), result["offset"], result["total"]), (20, 20, 120))
        status, data, headers = self.api(route + "/csv")
        self.assertEqual(status, 200)
        self.assertIn(b"attachment", headers)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(data.decode())))), 120)

    def test_frontend_assets_and_health_are_served(self):
        for path in ("/", "/app.js", "/app.css", "/favicon.svg", "/api/health"):
            status, body, headers = self.api(path)
            self.assertEqual(status, 200, path)
            self.assertGreater(len(body), 10)
            self.assertIn(b"Content-Security-Policy", headers)

    def test_invalid_requests_do_not_create_jobs(self):
        for value in (0, 601, True, "20", 1.5):
            self.assertEqual(self.api("/api/jobs/demo", "POST", {"max_frames": value})[0], 400)
        self.assertEqual(self.api("/api/jobs/demo", "POST", [], body=None)[0], 400)
        self.assertEqual(self.api("/api/jobs/demo", "POST", {"max_frames": 3, "extra": 1})[0], 400)
        self.assertEqual(self.store.list(), [])

    def test_cross_origin_host_and_missing_header_are_rejected(self):
        for headers in ({"Origin": "https://example.com"}, {"Host": "example.com:8000"}, {"X-VisionWeave-Request": ""}, {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.api("/api/jobs/demo", "POST", {"max_frames": 1}, headers)[0], 403)
        self.assertEqual(self.store.list(), [])

    def test_removed_video_endpoint_is_unavailable(self):
        self.assertEqual(self.api("/api/jobs/video", "POST", body=b"video")[0], 404)
        self.assertEqual(self.store.list(), [])

    def test_file_routes_cannot_escape_workspace(self):
        for path in ("/../video_pipeline.py", "/backend/server.py", "/api/jobs/../../README.md", "/results/workspace/jobs.sqlite3"):
            self.assertEqual(self.api(path)[0], 404)

    def test_queue_bound_and_cancellation(self):
        jobs = [self.store.create(max_frames=3) for _ in range(3)]
        with self.assertRaisesRegex(JobError, "Three runs"):
            self.store.create()
        self.store.cancel(jobs[0]["id"])
        self.store.submit(jobs[0]["id"])
        result = self.wait_done(jobs[0]["id"])
        self.assertEqual(result["status"], "cancelled")
        self.assertFalse((self.store.root / result["id"] / "detections.csv").exists())

    def test_cancellation_during_processing_discards_csv(self):
        started, release = threading.Event(), threading.Event()
        def slow_frames(count):
            for frame in demo_frames(count):
                started.set()
                release.wait(5)
                yield frame
        with patch("backend.jobs.demo_frames", slow_frames):
            job = self.store.create(max_frames=5)
            self.store.submit(job["id"])
            self.assertTrue(started.wait(5))
            self.store.cancel(job["id"])
            release.set()
            self.assertEqual(self.wait_done(job["id"])["status"], "cancelled")
        self.assertFalse((self.store.root / job["id"] / "detections.csv").exists())

    def test_restart_marks_unfinished_jobs_and_keeps_completed_runs(self):
        pending = self.store.create(max_frames=2)
        complete = self.store.create(max_frames=2)
        self.store.submit(complete["id"])
        self.assertEqual(self.wait_done(complete["id"])["status"], "completed")
        self.store.close()
        reopened = JobStore(self.store.root)
        try:
            self.assertEqual(reopened.get(pending["id"])["status"], "failed")
            self.assertEqual(reopened.get(complete["id"])["status"], "completed")
            self.assertEqual(reopened.results(complete["id"])["total"], 4)
        finally:
            reopened.close()

    def test_failed_adapter_never_exposes_partial_csv(self):
        with patch("backend.jobs.build_detectors", side_effect=RuntimeError("test failure")):
            job = self.store.create(max_frames=3)
            self.store.submit(job["id"])
            self.assertEqual(self.wait_done(job["id"])["status"], "failed")
        self.assertEqual(self.api(f'/api/jobs/{job["id"]}/csv')[0], 409)


if __name__ == "__main__":
    unittest.main()
