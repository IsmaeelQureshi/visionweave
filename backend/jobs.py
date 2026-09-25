"""Persistent job metadata, bounded execution, and shared pipeline integration."""

from __future__ import annotations

import csv
import json
import logging
import math
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from PIL import Image

from video_pipeline import build_detectors, demo_frames, process_frames

MAX_FRAMES = 600
TERMINAL = {"completed", "failed", "cancelled"}


class JobError(ValueError):
    pass


class Cancelled(Exception):
    pass


def bounded_int(value, name, low=1, high=MAX_FRAMES):
    if type(value) is not int or not low <= value <= high:
        raise JobError(f"{name} must be an integer between {low} and {high}.")
    return value


class JobStore:
    """One worker, at most three unfinished jobs; SQLite survives server restarts."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "jobs.sqlite3"
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.cancelled: set[str] = set()
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, created REAL, data TEXT)")
            for row in db.execute("SELECT id, data FROM jobs").fetchall():
                item = json.loads(row[1])
                if item["status"] not in TERMINAL:
                    item.update(status="failed", error="Server restarted before this run finished.")
                    db.execute("UPDATE jobs SET data=? WHERE id=?", (json.dumps(item), row[0]))
                    self.cleanup_incomplete(row[0])
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def get(self, job_id):
        # IDs never become arbitrary user-controlled paths.
        if not isinstance(job_id, str) or len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
            raise KeyError("Run not found")
        with self.connect() as db:
            row = db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError("Run not found")
        return json.loads(row[0])

    def list(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT data FROM jobs ORDER BY created DESC LIMIT 30")]

    def update(self, job_id, **values):
        with self.lock:
            data = self.get(job_id)
            data.update(values)
            with self.connect() as db:
                db.execute("UPDATE jobs SET data=? WHERE id=?", (json.dumps(data, allow_nan=False), job_id))
            return data

    def create(self, *, max_frames=120):
        bounded_int(max_frames, "Frame limit")
        with self.lock:
            if self.stopping.is_set():
                raise JobError("The server is shutting down.")
            with self.connect() as db:
                active = sum(json.loads(row[0])["status"] not in TERMINAL for row in db.execute("SELECT data FROM jobs"))
                if active >= 3:
                    raise JobError("Three runs are already queued. Wait for a run to finish.")
                job_id = uuid.uuid4().hex
                data = dict(id=job_id, name="Synthetic shapes", kind="demo",
                            status="queued",
                            created_at=time.time(), max_frames=max_frames,
                            frames=0, rows=0, boxes=0, points=0, empty=0,
                            elapsed_sec=0, fps=0, error=None, previews=[])
                (self.root / job_id).mkdir()
                db.execute("INSERT INTO jobs VALUES (?, ?, ?)", (job_id, data["created_at"], json.dumps(data)))
        return data

    def submit(self, job_id):
        self.update(job_id, status="queued")
        self.executor.submit(self.run, job_id)

    def cancel(self, job_id):
        with self.lock:
            data = self.get(job_id)
            if data["status"] not in TERMINAL:
                self.cancelled.add(job_id)
                self.update(job_id, status="cancelling")
        return self.get(job_id)

    def check_cancelled(self, job_id):
        if self.stopping.is_set() or job_id in self.cancelled:
            raise Cancelled()

    def cleanup_incomplete(self, job_id):
        directory = self.root / job_id
        (directory / "detections.csv").unlink(missing_ok=True)
        for path in directory.glob(".pipeline-*.tmp"):
            path.unlink(missing_ok=True)

    def run(self, job_id):
        start = time.perf_counter()
        directory = self.root / job_id
        counts = dict(frames=0, rows=0, boxes=0, points=0, empty=0)
        previews = []
        try:
            self.check_cancelled(job_id)
            job = self.update(job_id, status="running")
            interval = max(1, math.ceil(job["max_frames"] / 120))
            source = demo_frames(job["max_frames"])

            def checked_frames():
                try:
                    for frame in source:
                        self.check_cancelled(job_id)
                        yield frame
                finally:
                    source.close()

            def on_frame(frame, rows):
                self.check_cancelled(job_id)
                counts["frames"] += 1
                counts["rows"] += len(rows)
                for row in rows:
                    counts[{"box": "boxes", "point": "points", "empty": "empty"}[row["kind"]]] += 1
                if (counts["frames"] - 1) % interval == 0:
                    image = Image.fromarray(frame.rgb)
                    image.thumbnail((960, 540))
                    image.save(directory / f"frame-{frame.index}.jpg", quality=85)
                    previews.append(dict(index=frame.index, timestamp_sec=frame.timestamp_sec,
                                         width=frame.rgb.shape[1], height=frame.rgb.shape[0], rows=list(rows)))
                if counts["frames"] == 1 or counts["frames"] % 5 == 0:
                    elapsed = time.perf_counter() - start
                    self.update(job_id, **counts, previews=previews,
                                elapsed_sec=round(elapsed, 3), fps=round(counts["frames"] / max(elapsed, .001), 1))

            process_frames(checked_frames(), build_detectors(), directory / "detections.csv", on_frame=on_frame)
            # Serialize cancellation and terminal completion to avoid stale states.
            with self.lock:
                self.check_cancelled(job_id)
                elapsed = time.perf_counter() - start
                self.update(job_id, status="completed", **counts, previews=previews,
                            elapsed_sec=round(elapsed, 3), fps=round(counts["frames"] / max(elapsed, .001), 1))
        except Cancelled:
            self.cleanup_incomplete(job_id)
            self.update(job_id, status="cancelled", **counts, previews=previews)
        except Exception as exc:
            logging.exception("Run %s failed", job_id)
            self.cleanup_incomplete(job_id)
            message = str(exc) if isinstance(exc, (JobError, ValueError)) else "Processing failed. Check the server log and try again."
            self.update(job_id, status="failed", error=message, **counts, previews=previews)
        finally:
            with self.lock:
                self.cancelled.discard(job_id)

    def results(self, job_id, offset=0, limit=50):
        job = self.get(job_id)
        if job["status"] != "completed":
            raise JobError("Results are available when the run completes.")
        with (self.root / job_id / "detections.csv").open(newline="", encoding="utf-8") as handle:
            rows = []
            for index, row in enumerate(csv.DictReader(handle)):
                if index >= offset:
                    rows.append(row)
                if len(rows) == limit:
                    break
        return {"rows": rows, "total": job["rows"], "offset": offset, "limit": limit}

    def close(self):
        self.stopping.set()
        self.executor.shutdown(wait=True)
