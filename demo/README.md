# VisionWeave browser demo

A standalone synthetic demo of VisionWeave. Serve this directory with any static HTTPS host; no build, Python backend, accounts, database, or API keys are required.

Visitors can run 1–600 generated frames, cancel processing, inspect up to 120 previews with independent overlays, browse result rows, and download CSV. A Web Worker performs actual color-threshold detection on generated pixels. Progress reflects processed frames. The latest eight runs are kept in page memory and disappear on reload. No videos can be uploaded.

This JavaScript edition demonstrates the workflow, not trained-model accuracy or Python backend performance. It uses the same scene schedule and CSV columns as the Python project, but detects directly at source resolution. The Python version resizes to different adapter input sizes; its interpolation and ellipse rasterization can produce slightly different coordinates.

## Preview

From the project root: `python3 -m http.server 8001 --bind 127.0.0.1 --directory demo`.

Open http://127.0.0.1:8001. The hosted version uses HTTPS. Browser module scripts and module workers require HTTP(S), not a file URL.

## Checks

From the project root: `node --test tests/browser/engine.test.mjs`.

Tests cover known coordinates, detection from independent pixel inputs, missing shapes, normalized coordinates, and the 240-row CSV contract. The local Python app remains in `web/` and `backend/`.
