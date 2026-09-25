"""Behavior checks for geometry, orchestration, output safety, and video input."""

import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from video_pipeline import (
    DemoBoxDetector, Frame, Prediction, build_detectors, demo_frames,
    main, prediction_row, prepare_frame, process_frames, video_frames,
)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / "result.csv"

    def read_rows(self):
        with self.output.open(newline="") as handle:
            return list(csv.DictReader(handle))

    def test_letterbox_round_trip_handles_rounding_and_aspect_ratio(self):
        for width, height in ((853, 479), (113, 727), (1, 900), (200, 200)):
            with self.subTest(width=width, height=height):
                p = prepare_frame(np.zeros((height, width, 3), np.uint8), 224)
                self.assertEqual(p.tensor.shape, (1, 3, 224, 224))
                self.assertEqual(p.tensor.dtype, np.float32)
                t = p.transform
                for nx, ny in ((0, 0), (0.27, 0.73), (1, 1)):
                    x = t.pad_x + nx * t.resized_width
                    y = t.pad_y + ny * t.resized_height
                    ox, oy = t.to_original(x, y)
                    self.assertAlmostEqual(ox, nx * width)
                    self.assertAlmostEqual(oy, ny * height)
                self.assertEqual(t.to_original(-100, -100), (0, 0))

    def test_two_adapters_export_independent_rows_and_empty_frames(self):
        self.assertEqual(process_frames(demo_frames(60), build_detectors(), self.output), (60, 120))
        rows = self.read_rows()
        self.assertEqual({r["adapter"] for r in rows}, {"demo_box", "demo_point"})
        self.assertEqual(sum(r["kind"] == "empty" for r in rows), 30)
        for row in rows:
            self.assertEqual(row["confidence"], "")
            if row["kind"] != "empty":
                for key in ("x1_norm", "y1_norm", "x2_norm", "y2_norm"):
                    self.assertTrue(0 <= float(row[key]) <= 1)
        box, point = rows[:2]
        for actual, expected in zip((box[k] for k in ("x1", "y1", "x2", "y2")), (35, 80, 121, 146)):
            self.assertAlmostEqual(float(actual), expected, delta=3)
        self.assertAlmostEqual(float(point["x1"]), 320.5, delta=3)
        self.assertAlmostEqual(float(point["y1"]), 270.5, delta=3)
        self.assertEqual(point["x1"], point["x2"])

    def test_variable_detection_counts_do_not_pair_or_drop_results(self):
        class MultiBox(DemoBoxDetector):
            def predict(self, frame):
                return [Prediction("box", f"object_{i}", (10, 10, 20, 20)) for i in range(5)]
        detectors = (MultiBox(), build_detectors()[1])
        self.assertEqual(process_frames(demo_frames(1), detectors, self.output), (1, 6))
        self.assertEqual(len({r["label"] for r in self.read_rows()}), 6)

    def test_failure_preserves_existing_output_and_closes_source(self):
        class FailingDetector(DemoBoxDetector):
            def predict(self, frame):
                raise RuntimeError("adapter failed")
        closed = []

        def source():
            try:
                yield next(demo_frames(1))
            finally:
                closed.append(True)

        self.output.write_text("previous result")
        with self.assertRaisesRegex(RuntimeError, "adapter failed"):
            process_frames(source(), (FailingDetector(),), self.output, overwrite=True)
        self.assertEqual(self.output.read_text(), "previous result")
        self.assertEqual(closed, [True])
        self.assertEqual(list(self.output.parent.glob(".pipeline-*")), [])

    def test_existing_output_and_empty_source_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "No frames"):
            process_frames([], build_detectors(), self.output)
        self.assertFalse(self.output.exists())
        self.output.write_text("keep me")
        with self.assertRaises(FileExistsError):
            process_frames(demo_frames(1), build_detectors(), self.output)
        self.assertEqual(self.output.read_text(), "keep me")

    def test_invalid_adapter_results_fail_explicitly(self):
        frame = next(demo_frames(1))
        transform = prepare_frame(frame.rgb, 224).transform
        for prediction in (
            Prediction("box", "bad", (float("nan"), 0, 1, 1)),
            Prediction("box", "bad", (10, 0, 1, 1)),
            Prediction("point", "bad", (0, 0, 1, 1)),
            Prediction("box", "bad", (0, 0, 1, 1), confidence=2),
        ):
            with self.assertRaises(ValueError):
                prediction_row(frame, "test", 0, prediction, transform)

    def test_cli_demo_and_invalid_limits(self):
        self.assertEqual(main(["--demo", "--max-frames", "3", "--output", str(self.output)]), 0)
        self.assertEqual(len(self.read_rows()), 6)
        with self.assertRaises(SystemExit) as exc:
            main(["--demo", "--max-frames", "0"])
        self.assertEqual(exc.exception.code, 2)

    def test_video_sampling_unknown_fps_and_capture_cleanup(self):
        # Test source behavior without depending on a platform video decoder.
        class Capture:
            released = False
            reads = 0

            def isOpened(self): return True
            def get(self, _): return float("nan")
            def release(self): self.released = True
            def read(self):
                self.reads += 1
                return True, np.zeros((12, 20, 3), np.uint8)

        class FakeCV2:
            CAP_PROP_FPS = 5
            COLOR_BGR2RGB = 4
            def VideoCapture(self, _): return capture
            def cvtColor(self, array, _): return array[:, :, ::-1]

        capture = Capture()
        video = self.output.with_suffix(".avi")
        video.touch()
        with patch.dict("sys.modules", {"cv2": FakeCV2()}):
            frames = list(video_frames(video, stride=3, max_frames=2))
        self.assertEqual([f.index for f in frames], [0, 3])
        self.assertTrue(all(f.timestamp_sec is None for f in frames))
        self.assertTrue(capture.released)
        self.assertEqual(capture.reads, 4)

    @unittest.skipUnless(importlib.util.find_spec("cv2"), "optional OpenCV dependency is absent")
    def test_real_video_decode_and_csv(self):
        import cv2
        video = self.output.with_suffix(".avi")
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 30, (640, 360))
        self.assertTrue(writer.isOpened(), "MJPEG encoder must be available")
        try:
            for frame in demo_frames(8):
                writer.write(cv2.cvtColor(frame.rgb, cv2.COLOR_RGB2BGR))
        finally:
            writer.release()
        frames = list(video_frames(video, stride=2, max_frames=3))
        self.assertEqual([f.index for f in frames], [0, 2, 4])
        self.assertAlmostEqual(frames[-1].timestamp_sec, 4 / 30)
        self.assertEqual(process_frames(frames, build_detectors(), self.output), (3, 6))
        self.assertEqual({r["kind"] for r in self.read_rows()}, {"box", "point"})


if __name__ == "__main__":
    unittest.main()
