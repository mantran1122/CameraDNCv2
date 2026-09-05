import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
import main  # noqa: E402


class RtspUrlEncodingTest(unittest.TestCase):
    def test_live_url_encodes_special_characters_in_credentials(self):
        captured_urls = []

        class FakeCapture:
            def __init__(self, url, *_args):
                captured_urls.append(url)

            def isOpened(self):
                return False

            def release(self):
                pass

        with patch.object(config, "DEMO_MODE", False), \
             patch.object(config, "NVR_USER", "camera user"), \
             patch.object(config, "NVR_PASSWORD", "pass@word:1"), \
             patch.object(main.cv2, "VideoCapture", FakeCapture):
            list(main.generate_frames(1))

        self.assertIn("camera%20user:pass%40word%3A1@", captured_urls[0])

