"""Real socket smoke test for unrestricted local environments and CI."""

import json
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

from backend.jobs import JobStore
from backend.server import Server


def main():
    with tempfile.TemporaryDirectory() as directory:
        store = JobStore(Path(directory))
        server = Server(("127.0.0.1", 0), store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base + "/", timeout=10) as response:
                assert response.status == 200 and b"VisionWeave" in response.read()
            request = Request(base + "/api/jobs/demo", data=b'{"max_frames":12}',
                              headers={"Content-Type": "application/json", "X-VisionWeave-Request": "1"})
            with urlopen(request, timeout=10) as response:
                assert response.status == 202
                job = json.load(response)
            route = base + "/api/jobs/" + job["id"]
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                with urlopen(route, timeout=10) as response:
                    job = json.load(response)
                if job["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(.05)
            assert job["status"] == "completed", job
            assert job["frames"] == 12 and job["rows"] == 24
            with urlopen(route + "/csv", timeout=10) as response:
                assert len(response.read().splitlines()) == 25
            print("HTTP smoke test passed: UI, demo job, status polling, and CSV download.")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            store.close()


if __name__ == "__main__":
    main()
