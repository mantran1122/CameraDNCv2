from pathlib import Path
import sys
import unittest

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from student_affairs.detector import StudentAffairsDetector


class _FakeUniformDetector:
    def detect_people(self, image):
        return [{"bbox": [10, 20, 50, 80], "confidence": 0.9, "yellow_score": 0.7, "blue_score": 0.1}]


class StudentAffairsDetectorTests(unittest.TestCase):
    def test_returns_person_candidates_with_normalized_footpoint(self):
        people = StudentAffairsDetector(_FakeUniformDetector()).detect(Image.new("RGB", (100, 100)))
        self.assertEqual(len(people), 1)
        self.assertEqual(people[0].bbox, (10, 20, 50, 80))
        self.assertEqual(people[0].footpoint, (0.3, 0.8))
        self.assertEqual(people[0].yellow_score, 0.7)


if __name__ == "__main__":
    unittest.main()
