import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audio_analysis_worker  # noqa: E402
import config  # noqa: E402
import database  # noqa: E402


class AudioAnalysisWorkerTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        self.original_post_buffer = config.POST_BUFFER_SEC
        self.original_clips_dir = config.CLIPS_DIR
        self.original_suggestion_url = config.AUDIO_SUGGESTION_API_URL
        database.DB_PATH = Path(self.temp_dir.name) / "camera_metadata.db"
        config.POST_BUFFER_SEC = 0
        config.CLIPS_DIR = Path(self.temp_dir.name) / "clips"
        config.CLIPS_DIR.mkdir()
        config.AUDIO_SUGGESTION_API_URL = ""
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        config.POST_BUFFER_SEC = self.original_post_buffer
        config.CLIPS_DIR = self.original_clips_dir
        config.AUDIO_SUGGESTION_API_URL = self.original_suggestion_url
        self.temp_dir.cleanup()

    def test_clip_without_audio_is_recorded_as_no_audio_track(self):
        event_id = database.save_event(
            event_code="SoundDetection",
            event_type="audio_anomaly",
            channel=1,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            description="Sound detected",
            clip_filename="event.mp4",
        )
        (config.CLIPS_DIR / "event.mp4").write_bytes(b"placeholder")
        database.create_audio_analysis(event_id)
        worker = audio_analysis_worker.AudioAnalysisWorker()

        with patch.object(worker, "_has_audio_stream", return_value=False):
            worker._process(event_id)

        analysis = database.get_audio_analysis(event_id)
        event = database.get_event_by_id(event_id)
        self.assertEqual(analysis["status"], "no_audio_track")
        self.assertEqual(analysis["ignored_reason"], "no_audio_track")
        self.assertEqual(event["clip_filename"], "event.mp4")

    def test_existing_clip_is_used_for_manual_analysis(self):
        event_id = database.save_event(
            event_code="FightSound",
            event_type="audio_anomaly",
            channel=7,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            description="Sound detected",
            clip_filename="reviewable.mp4",
        )
        (config.CLIPS_DIR / "reviewable.mp4").write_bytes(b"placeholder")
        database.create_audio_analysis(event_id)
        worker = audio_analysis_worker.AudioAnalysisWorker()

        with patch.object(worker, "_has_audio_stream", return_value=False):
            worker._process(event_id)

        self.assertEqual(database.get_audio_analysis(event_id)["status"], "no_audio_track")

    def test_quiet_audio_skips_stt(self):
        event_id = database.save_event("HumanTrait", "video_anomaly", 1, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Alert", clip_filename="quiet.mp4")
        (config.CLIPS_DIR / "quiet.mp4").write_bytes(b"placeholder")
        wav_path = config.CLIPS_DIR / "quiet.wav"
        wav_path.write_bytes(b"placeholder")
        database.create_audio_analysis(event_id)
        worker = audio_analysis_worker.AudioAnalysisWorker()
        with patch.object(worker, "_has_audio_stream", return_value=True), \
             patch.object(worker, "_extract_wav", return_value=str(wav_path)), \
             patch.object(worker, "_wav_rms_dbfs", return_value=-70), \
             patch.object(worker, "_transcribe") as transcribe:
            worker._process(event_id)
        self.assertEqual(database.get_audio_analysis(event_id)["status"], "audio_too_quiet")
        transcribe.assert_not_called()

    def test_missing_evidence_is_reported_without_downloading_or_stt(self):
        event_id = database.save_event("Intrusion", "video_anomaly", 1, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Alert")
        database.create_audio_analysis(event_id)
        worker = audio_analysis_worker.AudioAnalysisWorker()
        worker._process(event_id)
        self.assertEqual(database.get_audio_analysis(event_id)["status"], "video_missing")

    def test_suggestion_is_grounded_and_validated(self):
        worker = audio_analysis_worker.AudioAnalysisWorker()
        old_url = config.AUDIO_SUGGESTION_API_URL
        old_key = config.AUDIO_SUGGESTION_API_KEY
        old_model = config.AUDIO_SUGGESTION_MODEL
        config.AUDIO_SUGGESTION_API_URL = "http://llm.test/v1/chat/completions"
        config.AUDIO_SUGGESTION_API_KEY = "test-key"
        config.AUDIO_SUGGESTION_MODEL = "test-model"
        response = Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": '{"summary":"Có tiếng nói ngắn.","risk_level":"low","recommended_action":"Kiểm tra clip.","evidence":[{"source":"audio transcript","detail":"Xin chào"}]}'}}]
        }
        try:
            with patch.object(audio_analysis_worker.requests, "post", return_value=response) as post:
                suggestion, error = worker._create_suggestion(
                    {"event_code": "SoundDetection", "description": "Sound", "metadata": {"Code": "SoundDetection"}},
                    {"transcript": "Xin chào", "speech_detected": 1, "ignored_reason": None},
                )
        finally:
            config.AUDIO_SUGGESTION_API_URL = old_url
            config.AUDIO_SUGGESTION_API_KEY = old_key
            config.AUDIO_SUGGESTION_MODEL = old_model

        self.assertIsNone(error)
        self.assertEqual(suggestion["risk_level"], "low")
        self.assertEqual(suggestion["evidence"][0]["source"], "audio transcript")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test-key")

    def test_gemini_combines_video_windows_and_audio_transcript(self):
        worker = audio_analysis_worker.AudioAnalysisWorker()
        expected = {
            "summary": "Có dấu hiệu cần kiểm tra.",
            "risk_level": "medium",
            "recommended_action": "Kiểm tra clip gốc.",
            "evidence": [{"source": "Cosmos", "detail": "Có chuyển động mạnh."}],
        }
        video = {"frames": [{"result": {"summary": "Có chuyển động mạnh."}}]}
        with patch.object(audio_analysis_worker, "get_gemini_public_config", return_value={"configured": True}), \
             patch.object(audio_analysis_worker.database, "get_video_analysis", return_value=video), \
             patch.object(audio_analysis_worker, "generate_final_video_report", return_value=(expected, "gemini-test")) as generate:
            suggestion, error = worker._create_suggestion(
                {"id": 7, "event_code": "ManualTest", "description": "Test"},
                {"transcript": "Dừng lại", "speech_detected": 1},
            )

        self.assertIsNone(error)
        self.assertEqual(suggestion, expected)
        self.assertEqual(generate.call_args.args[1], video["frames"])
        self.assertEqual(generate.call_args.args[2]["status"], "completed")
