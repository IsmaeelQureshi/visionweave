# 🎥 VisionWeave

*A synthetic frame-analysis workspace with interactive previews and CSV export*

VisionWeave analyzes a generated scene containing a moving red rectangle and green marker. Inspect detections frame by frame, toggle overlays, and download the results.

🔗 **Live Demo:** [Hosted on Vercel](https://visionweave-zeta.vercel.app/)

The detectors use simple color rules, **not trained AI models**. Both versions use only the generated scene; video uploads and video-file decoding are not supported.

---

## 🚀 Features

- Analyze up to 600 synthetic frames with progress and cancellation
- Inspect up to 120 frame previews with box and point overlays
- Play previews and browse paginated results
- Export pixel coordinates, normalized coordinates, and missing detections to CSV
- Keep saved runs in the local app, or up to eight temporary runs in the browser demo

## 🛠 Tech Stack

| Component | Technologies |
| --- | --- |
| Local backend | Python, SQLite, NumPy, Pillow |
| Interface | JavaScript, HTML, CSS, Canvas |
| Browser processing | JavaScript Web Worker |
| Hosting | Vercel, browser demo only |
| Tests | Python unittest, Node.js test runner, GitHub Actions |

## 🖥 Run Locally

```bash
git clone https://github.com/IsmaeelQureshi/visionweave.git
cd visionweave
python3 -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m backend.server
```

Open **http://127.0.0.1:8000** and click **Run analysis**. Press **Ctrl+C** to stop the server. Results and history are stored under `results/workspace/`.

The Python server is for local, single-user development. It processes one job at a time and accepts at most three unfinished jobs.

To export directly from the command line:

```bash
python video_pipeline.py --max-frames 120 --output results/demo.csv
```

Existing output is protected; use `--overwrite` to replace it after a successful run.

## 🌐 Browser Demo

The `demo/` folder runs entirely in the browser. It needs no backend, database, API keys, or build step. Its session history clears on reload.

To preview it locally:

```bash
python3 -m http.server 8001 --bind 127.0.0.1 --directory demo
```

Open **http://127.0.0.1:8001**. For Vercel, import the repository with **Root Directory: `demo`** and **Framework Preset: Other**. The included `vercel.json` handles the remaining build settings.

The browser detectors inspect source-resolution pixels. Python resizes each adapter's input and converts detections back to source coordinates, so the two versions can produce slightly different positions. Preview playback uses a fixed inspection speed, not source timing.

## 📁 Project Structure

```text
backend/           Local API, background jobs, and saved history
web/               Interface for the Python app
demo/              Standalone browser demo and Vercel settings
tests/             Pipeline, API, and browser detector tests
video_pipeline.py  Synthetic scene, detectors, coordinate conversion, and CSV
requirements.txt   Python dependencies
```

## ✅ Tests

```bash
python -m unittest discover -s tests -v
node --test tests/browser/engine.test.mjs
node --check web/app.js
node --check demo/app.js
```

GitHub Actions runs these checks, an HTTP smoke test, and a command-line demo. Tests cover coordinate conversion, missing detections, CSV output, validation, cancellation, and saved history.
