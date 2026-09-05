import os
import sys
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

# Ensure parent directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from live_service import (
    _has_speech_activity,
    _active_audio_model_id,
    _audio_beam_size,
    _audio_min_rms,
    _audio_transcripts_agree,
    _extract_and_parse_json,
    _is_duplicate_audio_transcript,
    _is_known_audio_hallucination,
    _is_repetitive_transcript,
    _last_audio_transcriptions,
    _pcm16_wav_rms,
)


class LiveAudioGuardTests(unittest.TestCase):
    def setUp(self):
        _last_audio_transcriptions.clear()

    @staticmethod
    def _wav(samples):
        pcm = np.asarray(samples, dtype="<i2").tobytes()
        return b"RIFF" + (b"\x00" * 36) + b"data" + struct.pack("<I", len(pcm)) + pcm

    def test_silence_has_zero_energy(self):
        wav = b"RIFF" + (b"\x00" * 36) + b"data" + struct.pack("<I", 400) + (b"\x00" * 400)
        self.assertEqual(_pcm16_wav_rms(wav), 0.0)

    def test_repetitive_whisper_loop_is_rejected(self):
        text = "Cảm ơn các bạn. " * 12
        self.assertTrue(_is_repetitive_transcript(text))

    def test_normal_vietnamese_sentence_is_kept(self):
        text = "Sinh viên vui lòng nộp hồ sơ tại bàn số hai trước khi nhận giấy xác nhận."
        self.assertFalse(_is_repetitive_transcript(text))

    def test_stationary_noise_is_not_speech(self):
        wav = self._wav(np.full(16000, 300, dtype=np.int16))
        detected, _, _ = _has_speech_activity(wav, 0.010)
        self.assertFalse(detected)

    def test_varying_voice_like_energy_is_speech(self):
        samples = np.zeros(16000, dtype=np.int16)
        t = np.arange(10000)
        samples[2000:12000] = (np.sin(2 * np.pi * 500 * t / 16000) * 8000).astype(np.int16)
        detected, _, active_seconds = _has_speech_activity(self._wav(samples), 0.010)
        self.assertTrue(detected)
        self.assertGreater(active_seconds, 0.4)

    def test_known_subscription_hallucination_is_rejected(self):
        self.assertTrue(_is_known_audio_hallucination(
            "Hãy subscribe cho kênh lalaschool để không bỏ lỡ những video hấp dẫn"
        ))

    def test_duplicate_across_chunks_is_rejected(self):
        text = "Mời sinh viên đến bàn số hai nhận hồ sơ."
        self.assertFalse(_is_duplicate_audio_transcript(text, "camera-1", "10", now=10))
        self.assertTrue(_is_duplicate_audio_transcript(text, "camera-1", "10", now=20))

    def test_vietnamese_model_and_beam_search_are_defaults(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(_active_audio_model_id(), "vinai/PhoWhisper-small")
            self.assertEqual(_audio_beam_size(), 5)
            self.assertEqual(_audio_min_rms(), 0.008)

    def test_audio_beam_size_is_bounded(self):
        with patch.dict("os.environ", {"COSMOS_AUDIO_BEAM_SIZE": "99"}):
            self.assertEqual(_audio_beam_size(), 10)

    def test_audio_rms_floor_blocks_unsafe_configuration(self):
        with patch.dict("os.environ", {"COSMOS_AUDIO_MIN_RMS": "0"}):
            self.assertEqual(_audio_min_rms(), 0.004)

    def test_decoder_disagreement_rejects_unstable_transcript(self):
        self.assertFalse(_audio_transcripts_agree(
            "nhiều doanh nghiệp hoàn toàn tỉnh bình dương",
            "một hai ba bốn năm",
        ))

    def test_decoder_agreement_keeps_same_spoken_text(self):
        self.assertTrue(_audio_transcripts_agree(
            "Một, hai, ba, bốn.", "một hai ba bốn"
        ))

    def test_json_parser_repairs_truncated_vllm_output(self):
        raw = '''{\n  "summary": "Eight individuals are present in the office, with four seated at desks and four standing. Seven people are working at desks equipped with computers, printers, and paperwork. One person'''
        result = _extract_and_parse_json(raw)
        self.assertIn("Eight individuals are present", result["summary"])
        self.assertEqual(result["risk_level"], "none")
        self.assertIsInstance(result["events"], list)

    def test_json_parser_handles_valid_json(self):
        raw = '{"summary": "Khu vực bình thường", "risk_level": "low", "events": [{"label": "nguoi", "count": 2}]}'
        result = _extract_and_parse_json(raw)
        self.assertEqual(result["summary"], "Khu vực bình thường")
        self.assertEqual(result["risk_level"], "low")
        self.assertEqual(len(result["events"]), 1)


if __name__ == "__main__":
    unittest.main()
