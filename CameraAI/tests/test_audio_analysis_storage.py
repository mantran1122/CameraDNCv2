import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database  # noqa: E402


class AudioAnalysisStorageTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        database.DB_PATH = Path(self.temp_dir.name) / "camera_metadata.db"
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_create_update_and_read_audio_analysis(self):
        event_id = database.save_event(
            event_code="SoundDetection",
            event_type="audio_anomaly",
            channel=1,
            timestamp="2026-08-31 10:00:00",
            description="Sound detected",
        )

        self.assertTrue(database.create_audio_analysis(event_id))
        self.assertFalse(database.create_audio_analysis(event_id))
        self.assertTrue(database.update_audio_analysis(
            event_id,
            status="completed",
            transcript="Xin chao",
            speech_detected=1,
            segments=[{"start": 0.0, "end": 1.0, "text": "Xin chao"}],
            suggestion={"risk_level": "low"},
            analyzed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        ))

        result = database.get_audio_analysis(event_id)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["transcript"], "Xin chao")
        self.assertEqual(result["segments"][0]["text"], "Xin chao")
        self.assertEqual(result["suggestion"]["risk_level"], "low")

    def test_finds_only_audio_alarms_with_a_clip_and_no_analysis(self):
        pending_id = database.save_event(
            event_code="FightSound", event_type="audio_anomaly", channel=7,
            timestamp="2026-08-31 10:00:00", description="Sound", clip_filename="event.mp4",
        )
        completed_id = database.save_event(
            event_code="SoundDetection", event_type="audio_anomaly", channel=1,
            timestamp="2026-08-31 10:01:00", description="Sound", clip_filename="done.mp4",
        )
        database.create_audio_analysis(completed_id)
        database.save_event(
            event_code="HumanTrait", event_type="normal_metadata", channel=1,
            timestamp="2026-08-31 10:02:00", description="Person", clip_filename="normal.mp4",
        )

        self.assertEqual(database.get_unanalyzed_audio_event_ids(), [pending_id])
