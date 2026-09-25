# Development verification

The full-stack edition was checked with the following results:

- **19 tests passed** across the shared pipeline and backend suite.
- **2 tests skipped** because OpenCV was unavailable: real video decoding, and real uploaded-video processing. Synthetic-frame processing and uploaded-byte handling were tested; a simulated decoder was explicitly used for the latter test.
- The actual HTTP request parser and handlers were tested with in-memory connections. Tests included creating a background demo job, reading status and JPEG previews, paginating results, and downloading a CSV.
- Frontend JavaScript syntax, referenced element IDs, and local asset paths passed static checks.
- A local listening server could not be started because the execution environment denied opening a port and rejected expanded permissions. Real socket testing, browser interaction testing, visual review, and experimental WebMCP verification were not completed here.
- A real HTTP smoke test and the video integration tests are included in GitHub Actions. That workflow has not been run here.

Run locally:

```bash
python -m pip install -r requirements-video.txt
python -m unittest discover -s tests -v
python -m tests.http_smoke
python -m backend.server
```

Open the server's printed address. Verify the synthetic demo, frame slider and overlay toggles, result pagination, CSV download, and a video upload on your machine.

This repository is a runnable local application. It has not been deployed to an online host.
