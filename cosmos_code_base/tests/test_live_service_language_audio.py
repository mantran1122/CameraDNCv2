import wave
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import live_service


def test_vietnamese_gate_rejects_english_caption_with_vietnamese_title():
    english = {"summary": 'Eight frames show a film titled "Ba đường luân hồi".', "risk_level": "none", "events": []}
    vietnamese = {"summary": "Có một nhóm người đang đứng trong khu vực tối.", "risk_level": "none", "events": []}

    assert live_service._result_is_vietnamese(english) is False
    assert live_service._result_is_vietnamese(vietnamese) is True
    assert live_service._result_is_vietnamese(live_service._vietnamese_result_fallback(english)) is True


def test_long_wav_is_split_below_whisper_limit(monkeypatch, tmp_path):
    wav_path = tmp_path / "long.wav"
    sample_rate = 16_000
    with wave.open(str(wav_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\x00\x00" * sample_rate * 61)

    durations = []

    def fake_transcriber(path, generate_kwargs):
        with wave.open(str(path), "rb") as source:
            durations.append(source.getnframes() / source.getframerate())
        return {"text": "đoạn âm thanh"}

    monkeypatch.setattr(live_service, "_audio_transcriber", fake_transcriber)
    result = live_service._transcribe_short_wav_chunks(str(wav_path), {"task": "transcribe"})

    assert durations == [25.0, 25.0, 11.0]
    assert len(result["chunks"]) == 3
    assert result["text"] == "đoạn âm thanh đoạn âm thanh đoạn âm thanh"
