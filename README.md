# 🎥 VisionWeave

*A video analysis workspace with an interactive browser demo, frame inspection, and structured CSV export*

VisionWeave lets users **run video analysis, inspect frame-by-frame detections, and export structured results**. It includes a full-stack local application built with a **Python backend** and a **JavaScript frontend**, plus a standalone browser demo ready for static hosting.

The included detectors use **deterministic color rules on synthetic shapes**, not trained AI models. They demonstrate the analysis workflow rather than general object-recognition accuracy.

🔗 **Live Demo:** [Hosted on Vercel](https://visionweave-zeta.vercel.app/)

---

## 🚀 Key Features

- **Interactive Browser Demo** → Analyze a generated scene directly in your browser, with no installation or uploads
- **Local Video Analysis** → Upload videos to the Python app with optional OpenCV support
- **Frame Inspector** → Scrub through sampled frames and play previews with independent box and point overlays
- **Analysis Controls** → Set frame limits, monitor processing progress, and cancel active runs
- **Structured Results** → Browse paginated detections with source coordinates, normalized coordinates, and explicit empty results
- **CSV Export** → Download complete results for further analysis
- **Run History** → Revisit saved runs in the local app; the browser demo retains its latest eight runs until reload
- **Extensible Pipeline** → Connect custom detectors through the Python adapter interface

---

## 🛠 Tech Stack

**Backend — Local Application**

- Language: Python 3.10+
- API: Python standard-library HTTP server
- Database: SQLite
- Processing: NumPy and Pillow
- Video Decoding: OpenCV — optional
- Background Jobs: ThreadPoolExecutor

**Frontend**

- Languages: JavaScript, HTML, and CSS
- Frame Rendering: HTML Canvas
- Styling: Responsive CSS
- Browser Demo Processing: Web Workers
- CSV Downloads: Browser Blob API
- Build Tools: None required

**Testing**

- Python: unittest
- JavaScript: Node.js test runner
- CI: GitHub Actions

---

## 🌐 Deployment

**Browser Demo → Hosted on Vercel**

The `demo/` folder is a standalone static website. It generates frames and runs color-based detection in the visitor’s browser, without a Python backend, database, or API keys.

To deploy:

1. Import this repository into Vercel.
2. Set **Root Directory** to `demo`.
3. Select **Other** as the Framework Preset.
4. Deploy using the included `demo/vercel.json`, which specifies no build command and serves the directory directly.

Configure Deployment Protection for the audience you want. A private GitHub repository does not automatically make the deployed website private.

**Full-Stack Application → Local Development**

The Python app runs on your computer and stores its job history locally. Its development server is not configured for public hosting. An online version with uploads would need production serving, access controls, storage management, and appropriate worker infrastructure.

The browser demo detects at source resolution; the Python adapters resize their inputs. Coordinates can differ slightly between the two editions. Neither edition includes trained model weights.

---

## 🖥 Local Development Setup

### 1️⃣ Clone the Repository

```bash
git clone https://github.com/IsmaeelQureshi/visionweave.git
cd visionweave
```

### 2️⃣ Run the Full-Stack Application

```bash
python3 -m venv .venv
source .venv/bin/activate

# Windows PowerShell:
# .venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt
python -m backend.server
```

Open **http://127.0.0.1:8000** and click **Run analysis** to try the synthetic scene.

To enable video uploads, stop the server, install the optional decoder, and restart:

```bash
python -m pip install -r requirements-video.txt
python -m backend.server
```

Uploaded videos use the same color-based demo detectors. They do not perform general object recognition.

### 3️⃣ Run the Standalone Browser Demo

From the repository root:

```bash
python3 -m http.server 8001 --bind 127.0.0.1 --directory demo
```

Open **http://127.0.0.1:8001**. This server only serves the static files; analysis runs in the browser. No Python packages or Node installation are needed for the preview.

Press **Ctrl+C** in the terminal to stop either server.

---

## ⚙️ Command-Line Usage

Run the shared Python pipeline without the web interface:

```bash
# Analyze the synthetic scene
python video_pipeline.py --demo --output results/demo.csv

# Analyze a video after installing the optional decoder
python video_pipeline.py --video your_video.mp4 --stride 3 --max-frames 100 --output results/video.csv
```

Existing output files are protected unless you pass `--overwrite`.

---

## 📁 Project Structure

```text
visionweave/
├── backend/           Python API, background jobs, and SQLite persistence
├── web/               Frontend for the local Python application
├── demo/              Standalone browser demo and Vercel configuration
├── tests/             Python tests and browser engine tests
├── examples/          Synthetic sample CSV
├── assets/            Synthetic demo animation
├── video_pipeline.py  Shared Python processing pipeline and CLI
└── requirements.txt   Core Python dependencies
```

---

## ✅ Run Tests

```bash
# Python pipeline and backend tests
python -m unittest discover -s tests -v

# Browser engine tests — requires Node.js
node --test tests/browser/engine.test.mjs

# Frontend syntax checks
node --check web/app.js
node --check demo/app.js
```

The tests cover coordinate handling, missing detections, CSV output, job lifecycle, and API validation. Optional video integration tests require OpenCV. See [verification notes](VERIFICATION.md) for earlier development checks.

---

## 📝 Usage Notes

- **Synthetic scene:** A moving red region and green marker disappear on different schedules to demonstrate missing detections.
- **Local limits:** Uploads are capped at 100 MB, runs at 600 sampled frames, and previews at 120 per run.
- **Local storage:** Results and job history remain under `results/workspace/`. Uploaded source videos are deleted after processing, cancellation, or failure.
- **Browser history:** Up to eight runs are retained in page memory and cleared on reload.
- **Playback:** Preview playback uses a fixed inspection speed rather than the original video timing.
- **Custom models:** Implement the `Detector` protocol and register adapters in `build_detectors()` inside `video_pipeline.py`.

See the [browser demo README](demo/README.md) for more details about the standalone edition.
