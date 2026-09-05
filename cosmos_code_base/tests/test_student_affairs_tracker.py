from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from student_affairs.tracker import CameraPersonTracker, CameraTrackerRegistry


@dataclass(frozen=True)
class Detection:
    bbox: tuple[int, int, int, int]
    confidence: float = 0.9
    yellow_score: float = 0.7
    blue_score: float = 0.1


class StudentAffairsTrackerTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 21, 10, 0, tzinfo=timezone(timedelta(hours=7)))

    def test_keeps_id_when_a_person_moves_slightly(self):
        tracker = CameraPersonTracker()
        first = tracker.update(self.now, [Detection((10, 20, 50, 100))], (200, 200))
        second = tracker.update(self.now + timedelta(seconds=1), [Detection((14, 20, 54, 100))], (200, 200))
        self.assertEqual(first[0].track_id, second[0].track_id)
        self.assertEqual(second[0].footpoint, (0.17, 0.5))

    def test_does_not_reuse_an_expired_track(self):
        tracker = CameraPersonTracker(max_age_seconds=3)
        first = tracker.update(self.now, [Detection((10, 20, 50, 100))], (200, 200))
        tracker.update(self.now + timedelta(seconds=4), [], (200, 200))
        returned = tracker.update(self.now + timedelta(seconds=5), [Detection((10, 20, 50, 100))], (200, 200))
        self.assertNotEqual(first[0].track_id, returned[0].track_id)

    def test_keeps_id_after_a_short_occlusion(self):
        tracker = CameraPersonTracker(max_age_seconds=3)
        first = tracker.update(self.now, [Detection((10, 20, 50, 100))], (200, 200))
        tracker.update(self.now + timedelta(seconds=1), [], (200, 200))
        returned = tracker.update(self.now + timedelta(seconds=2), [Detection((12, 20, 52, 100))], (200, 200))
        self.assertEqual(first[0].track_id, returned[0].track_id)

    def test_registry_isolates_track_ids_and_state_per_camera(self):
        registry = CameraTrackerRegistry()
        alpha = registry.for_camera("camera-a")
        beta = registry.for_camera("camera-b")
        self.assertIsNot(alpha, beta)
        alpha_id = alpha.update(self.now, [Detection((10, 20, 50, 100))], (200, 200))[0].track_id
        beta_id = beta.update(self.now, [Detection((110, 20, 150, 100))], (200, 200))[0].track_id
        self.assertEqual((alpha_id, beta_id), (1, 1))
        self.assertEqual(len(alpha.update(self.now + timedelta(seconds=1), [], (200, 200))), 0)
        self.assertEqual(beta.update(self.now + timedelta(seconds=1), [Detection((112, 20, 152, 100))], (200, 200))[0].track_id, 1)


if __name__ == "__main__":
    unittest.main()
