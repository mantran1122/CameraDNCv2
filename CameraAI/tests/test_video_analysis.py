import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
import database  # noqa: E402
import video_analysis_worker  # noqa: E402


class VideoAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        self.original_clips_dir = config.CLIPS_DIR
        database.DB_PATH = Path(self.temp_dir.name) / "camera_metadata.db"
        config.CLIPS_DIR = Path(self.temp_dir.name) / "clips"
        config.CLIPS_DIR.mkdir()
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        config.CLIPS_DIR = self.original_clips_dir
        self.temp_dir.cleanup()

    def _event(self, filename="event.mp4"):
        event_id = database.save_event(
            event_code="Intrusion",
            event_type="video_anomaly",
            channel=2,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            description="Alert",
            clip_filename=filename,
        )
        database.create_video_analysis(event_id)
        return event_id

    def test_video_analysis_storage_round_trip(self):
        event_id = self._event()
        database.update_video_analysis(
            event_id,
            status="completed",
            summary="Có hai người trong hành lang.",
            risk_level="low",
            events=[{"label": "nguoi", "count": 2}],
            frames=[{"offset_seconds": 5, "result": {"risk_level": "low"}}],
        )
        result = database.get_video_analysis(event_id)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["events"][0]["count"], 2)
        self.assertEqual(result["frames"][0]["offset_seconds"], 5)

    def test_aggregate_uses_highest_risk_and_max_count(self):
        result = video_analysis_worker.VideoAnalysisWorker._aggregate([
            {"result": {"summary": "Có hai người.", "risk_level": "low", "events": [{"label": "nguoi", "count": 2}]}},
            {"result": {"summary": "Có ba người và khói.", "risk_level": "high", "events": [{"label": "nguoi", "count": 3}, {"label": "khoi", "count": 1}]}},
        ])
        self.assertEqual(result["risk_level"], "high")
        self.assertEqual(result["events"], [{"label": "khoi", "count": 1}, {"label": "nguoi", "count": 3}])
        self.assertIn("Có hai người", result["summary"])

    def test_worker_analyzes_adaptive_sequences(self):
        event_id = self._event("reviewable.mp4")
        (config.CLIPS_DIR / "reviewable.mp4").write_bytes(b"placeholder")
        worker = video_analysis_worker.VideoAnalysisWorker()
        health = Mock(ok=True, status_code=200)
        health.json.return_value = {"status": "ready", "video_model": "nvidia/Cosmos-Reason2-2B"}
        sequence_results = [
            {"status": "ok", "inference_ms": 100, "result": {"summary": "Khung cảnh bình thường.", "risk_level": "none", "events": []}},
            {"status": "ok", "inference_ms": 120, "result": {"summary": "Có một người.", "risk_level": "low", "events": [{"label": "nguoi", "count": 1}]}},
        ]
        sequences = [
            {"start_seconds": 0.0, "end_seconds": 10.0, "frames": [(0.0, b"one"), (5.0, b"two")]},
            {"start_seconds": 10.0, "end_seconds": 20.0, "frames": [(10.0, b"three"), (15.0, b"four")]},
        ]
        with patch.object(worker, "_extract_adaptive_sequences", return_value=sequences), \
             patch.object(worker, "_analyze_sequence", side_effect=sequence_results), \
             patch.object(video_analysis_worker.requests, "get", return_value=health):
            worker._process(event_id)

        analysis = database.get_video_analysis(event_id)
        self.assertEqual(analysis["status"], "completed")
        self.assertEqual(analysis["risk_level"], "low")
        self.assertEqual(len(analysis["frames"]), 2)
        self.assertEqual(analysis["frames"][1]["window_start_seconds"], 10.0)
        self.assertEqual(analysis["video_model"], "nvidia/Cosmos-Reason2-2B")

    def test_missing_clip_is_terminal(self):
        event_id = self._event("missing.mp4")
        video_analysis_worker.VideoAnalysisWorker()._process(event_id)
        self.assertEqual(database.get_video_analysis(event_id)["status"], "video_missing")


if __name__ == "__main__":
    unittest.main()
