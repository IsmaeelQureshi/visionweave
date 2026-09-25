"""Process synthetic frames through independent box and point adapters into a common CSV.

Run: python video_pipeline.py --output results/demo.csv
Demo adapters use color rules, require no weights, and are not trained models.
Python 3.10+. See README.md for setup and usage.
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Literal, Protocol, Sequence

import numpy as np
from PIL import Image, ImageDraw

LOGGER = logging.getLogger("video_pipeline")
FIELDS = (
    "frame_index", "timestamp_sec", "frame_width", "frame_height", "adapter",
    "prediction_index", "kind", "label", "confidence", "visible",
    "x1", "y1", "x2", "y2", "x1_norm", "y1_norm", "x2_norm", "y2_norm",
)


@dataclass(frozen=True)
class Frame:
    index: int
    timestamp_sec: float | None
    rgb: np.ndarray


@dataclass(frozen=True)
class Transform:
    """Continuous edge coordinates: [0,width] x [0,height], not pixel indices."""

    width: int
    height: int
    resized_width: int
    resized_height: int
    pad_x: int
    pad_y: int

    def to_original(self, x: float, y: float) -> tuple[float, float]:
        # Use actual rounded resize dimensions independently on each axis.
        ox = (x - self.pad_x) * self.width / self.resized_width
        oy = (y - self.pad_y) * self.height / self.resized_height
        return min(max(ox, 0.0), self.width), min(max(oy, 0.0), self.height)


@dataclass(frozen=True)
class PreparedFrame:
    rgb: np.ndarray  # HWC uint8, padded square
    tensor: np.ndarray  # 1 x 3 x H x W float32, RGB in [0, 1]
    transform: Transform


@dataclass(frozen=True)
class Prediction:
    """Adapter output in padded-canvas edge coordinates, before inverse mapping.

    Points use x1 == x2 and y1 == y2. Confidence and visibility are optional:
    deterministic demo rules do not manufacture model confidence scores.
    """

    kind: Literal["box", "point"]
    label: str
    xyxy: tuple[float, float, float, float]
    confidence: float | None = None
    visible: bool | None = None


class Detector(Protocol):
    """Contract for adapters that return detections in prepared-frame coordinates."""

    name: str
    input_size: int

    def predict(self, frame: PreparedFrame) -> Sequence[Prediction]: ...


def prepare_frame(rgb: np.ndarray, target: int) -> PreparedFrame:
    """RGB conversion belongs to the source; resizing and scaling happen here."""
    if target < 1:
        raise ValueError("Input size must be positive")
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.dtype != np.uint8:
        raise ValueError("Frames must be HWC RGB uint8 arrays")
    height, width = rgb.shape[:2]
    if min(width, height) < 1:
        raise ValueError("Frame dimensions must be positive")
    scale = min(target / width, target / height)
    rw = max(1, min(target, round(width * scale)))
    rh = max(1, min(target, round(height * scale)))
    px, py = (target - rw) // 2, (target - rh) // 2
    resized = np.asarray(Image.fromarray(rgb).resize((rw, rh), Image.Resampling.BILINEAR))
    canvas = np.zeros((target, target, 3), dtype=np.uint8)
    canvas[py:py + rh, px:px + rw] = resized
    tensor = np.ascontiguousarray(canvas.transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
    return PreparedFrame(canvas, tensor, Transform(width, height, rw, rh, px, py))


class DemoBoxDetector:
    """Localize the single red region in the synthetic scene; no ML inference."""

    name = "demo_box"
    input_size = 320  # Each adapter owns its input size.

    def predict(self, frame: PreparedFrame) -> Sequence[Prediction]:
        r, g, b = frame.rgb.transpose(2, 0, 1)
        ys, xs = np.where((r > 180) & (g < 100) & (b < 100))
        if not xs.size:
            return []
        return [Prediction("box", "red_region", (
            float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1),
        ))]


class DemoPointDetector:
    """Find the centroid of a green marker independently of the box adapter."""

    name = "demo_point"
    input_size = 224

    def predict(self, frame: PreparedFrame) -> Sequence[Prediction]:
        r, g, b = frame.rgb.transpose(2, 0, 1)
        ys, xs = np.where((g > 180) & (r < 100) & (b < 100))
        if not xs.size:
            return []
        x, y = float(xs.mean() + 0.5), float(ys.mean() + 0.5)
        return [Prediction("point", "green_center", (x, y, x, y), visible=True)]


def build_detectors() -> tuple[Detector, ...]:
    """Create the independent red-region and green-marker detectors."""
    return DemoBoxDetector(), DemoPointDetector()


def demo_frames(count: int = 120) -> Iterator[Frame]:
    """Generate only geometric shapes. Deliberate gaps exercise empty results."""
    for index in range(count):
        image = Image.new("RGB", (640, 360), (20, 27, 40))
        draw = ImageDraw.Draw(image)
        if index % 60 < 50:
            left = 35 + (index * 3) % 400
            draw.rectangle((left, 80, left + 85, 145), fill=(235, 65, 65))
        if index % 60 < 40:
            cx = 320 + round(160 * math.sin(index / 16))
            draw.ellipse((cx - 12, 258, cx + 12, 282), fill=(65, 225, 85))
        yield Frame(index, index / 30.0, np.asarray(image))


def prediction_row(frame: Frame, adapter: str, number: int,
                   prediction: Prediction, transform: Transform) -> dict:
    """Validate adapter outputs, invert padding/resize, and normalize results."""
    p = prediction
    if p.kind not in ("box", "point") or not p.label:
        raise ValueError("Predictions need a supported kind and nonempty label")
    if len(p.xyxy) != 4 or not all(math.isfinite(v) for v in p.xyxy):
        raise ValueError("Prediction coordinates must contain four finite numbers")
    x1, y1, x2, y2 = p.xyxy
    if x2 < x1 or y2 < y1:
        raise ValueError("Box corners must be ordered")
    if p.kind == "point" and (x1 != x2 or y1 != y2):
        raise ValueError("Point predictions must repeat the same coordinate")
    if p.confidence is not None and not (math.isfinite(p.confidence) and 0 <= p.confidence <= 1):
        raise ValueError("Confidence must be absent or in [0, 1]")
    if p.visible is not None and type(p.visible) is not bool:
        raise ValueError("Visibility must be a bool or None")
    x1, y1 = transform.to_original(x1, y1)
    x2, y2 = transform.to_original(x2, y2)
    return {
        "adapter": adapter, "prediction_index": number, "kind": p.kind,
        "label": p.label, "confidence": p.confidence,
        "visible": None if p.visible is None else int(p.visible),
        "x1": round(x1, 4), "y1": round(y1, 4),
        "x2": round(x2, 4), "y2": round(y2, 4),
        "x1_norm": round(x1 / transform.width, 6),
        "y1_norm": round(y1 / transform.height, 6),
        "x2_norm": round(x2 / transform.width, 6),
        "y2_norm": round(y2 / transform.height, 6),
    }


def process_frames(frames: Iterable[Frame], detectors: Sequence[Detector],
                   output: Path, *, overwrite: bool = False,
                   progress_every: int = 30,
                   on_frame: Callable[[Frame, Sequence[dict]], None] | None = None) -> tuple[int, int]:
    """Stream to a temporary file; publish the CSV only after successful completion."""
    if not detectors or len({d.name for d in detectors}) != len(detectors):
        raise ValueError("Provide adapters with unique names")
    if any(not d.name or d.input_size < 1 for d in detectors):
        raise ValueError("Adapters need nonempty names and positive input sizes")
    if progress_every < 1:
        raise ValueError("Progress interval must be positive")
    if output.exists() and not overwrite:
        raise FileExistsError(f"Output exists: {output}; use --overwrite to replace it")
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    frame_count = row_count = 0
    temporary: Path | None = None
    iterator = iter(frames)
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="",
                                         dir=output.parent, prefix=".pipeline-",
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            for frame in iterator:
                frame_rows = []
                height, width = frame.rgb.shape[:2]
                base = {"frame_index": frame.index,
                        "timestamp_sec": None if frame.timestamp_sec is None else round(frame.timestamp_sec, 6),
                        "frame_width": width, "frame_height": height}
                for detector in detectors:
                    prepared = prepare_frame(frame.rgb, detector.input_size)
                    predictions = detector.predict(prepared)
                    # Each adapter has its own rows: no implied object association.
                    if not predictions:
                        row = {**base, "adapter": detector.name, "kind": "empty"}
                        writer.writerow(row)
                        frame_rows.append(row)
                        row_count += 1
                    for number, prediction in enumerate(predictions):
                        row = prediction_row(frame, detector.name, number, prediction, prepared.transform)
                        writer.writerow({**base, **row})
                        frame_rows.append({**base, **row})
                        row_count += 1
                frame_count += 1
                if on_frame is not None:
                    on_frame(frame, frame_rows)
                if frame_count % progress_every == 0:
                    elapsed = max(time.perf_counter() - started, 1e-9)
                    LOGGER.info("Processed %d frames | %d rows | %.1f frames/s",
                                frame_count, row_count, frame_count / elapsed)
            if not frame_count:
                raise ValueError("No frames were processed")
        if overwrite:
            os.replace(temporary, output)
        else:
            # Atomic no-clobber publication, even if output appeared during the run.
            os.link(temporary, output)
        LOGGER.info("Saved %d frames / %d rows to %s", frame_count, row_count, output)
        return frame_count, row_count
    finally:
        if hasattr(iterator, "close"):
            iterator.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=Path("results/detections.csv"))
    parser.add_argument("--max-frames", type=positive_int, help="maximum sampled frames (demo default: 120)")
    parser.add_argument("--progress-every", type=positive_int, default=30)
    parser.add_argument("--overwrite", action="store_true", help="replace existing output after success")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        LOGGER.info("Using deterministic demo adapters; no trained models or weights")
        frames = demo_frames(args.max_frames or 120)
        process_frames(frames, build_detectors(), args.output,
                       overwrite=args.overwrite, progress_every=args.progress_every)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        LOGGER.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        LOGGER.warning("Interrupted; no new CSV published")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
