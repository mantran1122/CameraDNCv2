import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database  # noqa: E402


class MetadataRetentionTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        database.DB_PATH = Path(self.temp_dir.name) / "camera_metadata.db"
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_removes_old_event_and_keeps_recent_event(self):
        old_time = (datetime.now() - timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S")
        recent_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        old_id = database.save_event("Intrusion", "video_anomaly", 1, old_time, "Old", clip_filename="old.mp4")
        recent_id = database.save_event("HumanTrait", "normal_metadata", 1, recent_time, "Recent")
        database.create_audio_analysis(old_id)
        self.assertEqual(database.delete_expired_events(3), ["old.mp4"])
        self.assertIsNone(database.get_event_by_id(old_id))
        self.assertIsNotNone(database.get_event_by_id(recent_id))
        self.assertIsNone(database.get_audio_analysis(old_id))

    def test_purge_expired_day_folders_calendar_logic(self):
        import config
        import main

        original_clips_dir = config.CLIPS_DIR
        config.CLIPS_DIR = Path(self.temp_dir.name) / "clips"
        try:
            # 35 days ago (should be purged) and 5 days ago (should be kept)
            old_date = datetime.now().date() - timedelta(days=35)
            recent_date = datetime.now().date() - timedelta(days=5)

            old_folder = config.CLIPS_DIR / "cameras" / "cam-003" / f"{old_date.year}" / f"{old_date.month:02d}" / f"{old_date.day:02d}"
            recent_folder = config.CLIPS_DIR / "cameras" / "cam-003" / f"{recent_date.year}" / f"{recent_date.month:02d}" / f"{recent_date.day:02d}"

            old_folder.mkdir(parents=True, exist_ok=True)
            recent_folder.mkdir(parents=True, exist_ok=True)
            (old_folder / "old.mp4").write_bytes(b"data")
            (recent_folder / "recent.mp4").write_bytes(b"data")

            summary = main.purge_expired_metadata(retention_days=30)
            self.assertEqual(summary["status"], "success")
            self.assertFalse(old_folder.exists(), "Old folder should be purged")
            self.assertTrue(recent_folder.exists(), "Recent folder should be preserved")
        finally:
            config.CLIPS_DIR = original_clips_dir
