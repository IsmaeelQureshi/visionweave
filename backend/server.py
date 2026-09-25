"""Same-origin local HTTP API. Designed for one user on loopback, not public hosting.

Run from the repository root: python -m backend.server
"""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import re
import shutil
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from backend.jobs import JobError, JobStore, bounded_int

WEB = Path(__file__).resolve().parents[1] / "web"
ASSETS = {"/": "index.html", "/app.js": "app.js", "/app.css": "app.css", "/favicon.svg": "favicon.svg"}


class APIError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store):
        self.store = store
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "VisionWeave/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(60)

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        try:
            port = self.server.server_port
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in hosts:
                raise APIError(403, "Use the local workspace address printed by the server.")
            if method == "POST":
                origin = self.headers.get("Origin")
                if origin and origin not in {f"http://{host}" for host in hosts}:
                    raise APIError(403, "Cross-origin requests are not allowed.")
                if self.headers.get("Sec-Fetch-Site") == "cross-site":
                    raise APIError(403, "Cross-site requests are not allowed.")
                if self.headers.get("X-VisionWeave-Request") != "1":
                    raise APIError(403, "Missing workspace request header.")
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            if method == "GET":
                self.get_route(url.path, query)
            else:
                self.post_route(url.path, query)
        except APIError as exc:
            self.send_json(exc.status, {"error": exc.message})
        except KeyError:
            self.send_json(404, {"error": "Run or resource not found."})
        except (JobError, ValueError) as exc:
            self.send_json(400, {"error": str(exc)})
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True
        except Exception:
            logging.exception("Request failed")
            self.send_json(500, {"error": "The server could not complete this request."})

    def response_headers(self, status, content_type, length):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")

    def send_json(self, status, data):
        payload = json.dumps(data, allow_nan=False).encode("utf-8")
        self.response_headers(status, "application/json; charset=utf-8", len(payload))
        self.end_headers()
        self.wfile.write(payload)

    def send_file(self, path, *, download=False):
        if not path.is_file():
            raise KeyError("File not found")
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.response_headers(200, mime, path.stat().st_size)
        if download:
            self.send_header("Content-Disposition", 'attachment; filename="detections.csv"')
        self.end_headers()
        with path.open("rb") as handle:
            shutil.copyfileobj(handle, self.wfile)

    def read_length(self, maximum):
        if self.headers.get("Transfer-Encoding"):
            raise APIError(400, "Chunked request bodies are not supported.")
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            raise APIError(400, "Invalid content length.")
        if length < 1:
            raise APIError(400, "Request body is empty.")
        if length > maximum:
            raise APIError(413, "Request body is too large.")
        return length

    def get_route(self, path, query):
        store = self.server.store
        if path in ASSETS:
            return self.send_file(WEB / ASSETS[path])
        if path == "/api/health":
            return self.send_json(200, {"status": "ok"})
        if path == "/api/jobs":
            return self.send_json(200, {"jobs": [{k: v for k, v in job.items() if k != "previews"} for job in store.list()]})
        match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})(?:/(results|csv|frames/(\d+)\.jpg))?", path)
        if match is None:
            raise KeyError("Unknown route")
        job_id, action, index = match.groups()
        job = store.get(job_id)
        if not action:
            return self.send_json(200, job)
        if action == "results":
            offset = bounded_int(int(query.get("offset", ["0"])[0]), "Offset", low=0, high=1000000)
            limit = bounded_int(int(query.get("limit", ["50"])[0]), "Page size", high=100)
            return self.send_json(200, store.results(job_id, offset, limit))
        if action == "csv":
            if job["status"] != "completed":
                raise APIError(409, "CSV export is available after the run completes.")
            return self.send_file(store.root / job_id / "detections.csv", download=True)
        if not any(p["index"] == int(index) for p in job["previews"]):
            raise KeyError("Unknown frame")
        return self.send_file(store.root / job_id / f"frame-{int(index)}.jpg")

    def post_route(self, path, query):
        store = self.server.store
        match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})/cancel", path)
        if match:
            return self.send_json(200, store.cancel(match.group(1)))
        if path == "/api/jobs/demo":
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise APIError(415, "Send JSON for demo runs.")
            length = self.read_length(4096)
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict) or set(data) - {"max_frames"}:
                raise APIError(400, "Provide a JSON object with max_frames only.")
            job = store.create(max_frames=data.get("max_frames", 120))
            store.submit(job["id"])
            return self.send_json(202, store.get(job["id"]))
        raise KeyError("Unknown route")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", type=Path, default=Path("results/workspace"))
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    store = JobStore(args.data_dir)
    try:
        server = Server(("127.0.0.1", args.port), store)
    except OSError as exc:
        store.close()
        parser.exit(1, f"Could not start the local server: {exc}\nTry a different --port if it is already in use.\n")
    print(f"VisionWeave is running at http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()


if __name__ == "__main__":
    main()
