from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from student_affairs.config import load_camera_profile
from student_affairs.rules import StudentAffairsRules, TrackObservation


PROFILE = PROJECT_ROOT / "configs" / "cameras" / "student_affairs_pilot.yaml"


class StudentAffairsRuleTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_camera_profile(PROFILE)
        self.rules = StudentAffairsRules(self.profile)
        self.now = datetime(2026, 8, 21, 10, 0, tzinfo=timezone(timedelta(hours=7)))

    def test_uncovered_alert_waits_for_configured_duration_and_is_deduplicated(self):
        initial = self.rules.update(self.now, [])
        self.assertEqual(initial["desks"][0]["status"], "uncovered_pending")
        before = self.rules.update(self.now + timedelta(seconds=89), [])
        self.assertEqual(before["alerts"], [])
        alert = self.rules.update(self.now + timedelta(seconds=90), [])
        self.assertEqual(alert["alerts"][0]["id"], "desk_01_uncovered")
        self.assertEqual(self.rules.update(self.now + timedelta(seconds=91), [])["alerts"], [])

    def test_staff_at_desk_covers_it(self):
        frame = self.rules.update(self.now, [TrackObservation(7, (0.3, 0.3), 0.9)])
        self.assertEqual(frame["desks"][0], {"id": "desk_01", "status": "covered", "staff_tracks": [7]})

    def test_scene_change_disables_zone_rules(self):
        frame = self.rules.update(self.now, [], scene_changed=True)
        self.assertEqual(frame["scene_status"], "needs_recalibration")
        self.assertEqual(frame["alerts"], [])


if __name__ == "__main__":
    unittest.main()
