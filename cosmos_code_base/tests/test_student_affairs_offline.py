from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from student_affairs.config import load_camera_profile
from student_affairs.detector import PersonCandidate
from student_affairs.offline import StudentAffairsPipeline, draw_overlay, zone_for_track


PROFILE = PROJECT_ROOT / "configs" / "cameras" / "student_affairs_pilot.yaml"


class FakeDetector:
    def __init__(self):
        self.calls = 0

    def detect(self, image):
        self.calls += 1
        return [PersonCandidate((25 + self.calls, 20, 75 + self.calls, 100), 0.9, 0.8, 0.1, (0.0, 0.0))]


class StudentAffairsOfflineTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_camera_profile(PROFILE)
        self.now = datetime(2026, 8, 21, 10, 0, tzinfo=timezone(timedelta(hours=7)))

    def test_pipeline_composes_detector_tracker_and_rules(self):
        pipeline = StudentAffairsPipeline(self.profile, FakeDetector())
        first = pipeline.process(Image.new("RGB", (200, 200)), self.now)
        second = pipeline.process(Image.new("RGB", (200, 200)), self.now + timedelta(seconds=1))
        self.assertEqual(first.tracks[0].track_id, second.tracks[0].track_id)
        self.assertEqual(second.event["desks"][0]["status"], "covered")
        self.assertEqual(zone_for_track(second.tracks[0], self.profile), "desk_01")

    def test_overlay_keeps_frame_shape(self):
        pipeline = StudentAffairsPipeline(self.profile, FakeDetector())
        analysis = pipeline.process(Image.new("RGB", (200, 200)), self.now)
        frame = np.zeros((200, 200, 3), dtype=np.uint8)
        overlay = draw_overlay(frame, analysis, self.profile)
        self.assertEqual(overlay.shape, frame.shape)
        self.assertFalse(np.array_equal(overlay, frame))


if __name__ == "__main__":
    unittest.main()
