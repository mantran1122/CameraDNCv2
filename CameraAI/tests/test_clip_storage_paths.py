from datetime import datetime
import unittest
from unittest.mock import patch

import clip_storage


class ClipStoragePathTests(unittest.TestCase):
    def test_reference_uses_capture_day_at_midnight_boundary(self):
        # The evidence clip finishes after midnight even though its queued
        # source event occurred on the previous calendar day.
        capture_time = datetime(2026, 9, 30, 0, 0, 1)
        reference = clip_storage.build_clip_reference(18, capture_time, 49570)
        self.assertEqual(
            reference,
            "cameras/cam-018/2026/09/30/evt_cam-018_20260930T000001_49570.mp4",
        )

    def test_storage_timestamp_uses_configured_timezone(self):
        with patch("clip_storage.datetime") as mocked_datetime:
            mocked_datetime.now.return_value = datetime(2026, 9, 30, 7, 0, 0)
            value = clip_storage.storage_timestamp()
        mocked_datetime.now.assert_called_once()
        self.assertEqual(value.date().isoformat(), "2026-09-30")


if __name__ == "__main__":
    unittest.main()
