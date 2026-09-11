import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
import internal_audio_client
from internal_audio_client import send_clean_audio_to_server, _normalize_audio_response


class InternalAudioClientTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sample_wav = Path(self.temp_dir.name) / "clean_sample.wav"
        self.sample_wav.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_raises_on_missing_file(self):
        with self.assertRaises(ValueError):
            send_clean_audio_to_server("non_existent_file.wav")

    def test_successful_server_response(self):
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "transcript": "Ai đang ở ngoài cổng đấy?",
            "speech_detected": 1,
            "detected_sounds": ["tiếng bước chân", "tiếng gọi"],
            "risk_level": "medium",
            "summary": "Phát hiện người gọi ngoài cổng.",
            "audio_model": "Internal Audio AI (Server H200)",
        }

        with patch("internal_audio_client.requests.post", return_value=mock_resp) as mock_post:
            result = send_clean_audio_to_server(str(self.sample_wav), event={"channel": 11, "event_code": "Intrusion"})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["transcript"], "Ai đang ở ngoài cổng đấy?")
        self.assertEqual(result["speech_detected"], 1)
        self.assertEqual(result["risk_level"], "medium")
        self.assertIn("tiếng bước chân", result["detected_sounds"])
        self.assertEqual(result["audio_model"], "Internal Audio AI (Server H200)")
        self.assertTrue(mock_post.called)

    def test_normalize_audio_response_defaults(self):
        norm = _normalize_audio_response({"text": "Xin chào"}, latency_ms=150)
        self.assertEqual(norm["transcript"], "Xin chào")
        self.assertEqual(norm["speech_detected"], 1)
        self.assertEqual(norm["risk_level"], "none")
        self.assertEqual(norm["latency_ms"], 150)


if __name__ == "__main__":
    unittest.main()

