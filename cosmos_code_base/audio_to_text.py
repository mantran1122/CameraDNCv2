import argparse
import sys
from pathlib import Path

import torch


def extract_audio(video_path: str, audio_path: str = None) -> str:
    import subprocess
    import os

    if audio_path is None:
        temp_dir = os.path.join(os.path.dirname(video_path), "temp_audio")
        os.makedirs(temp_dir, exist_ok=True)
        audio_path = os.path.join(temp_dir, "audio_extracted.wav")

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        "-f", "wav", audio_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed: {result.stderr}")
    return audio_path


def transcribe_video(
    video_path: str,
    model_id: str = "openai/whisper-base",
    device: str = None,
    translate: bool = False,
    language: str | None = None,
    max_new_tokens: int = 512,
    chunk_length_s: int = 30,
    stride_length_s: int = 5,
    no_repeat_ngram_size: int = 3,
) -> dict:
    """Extract audio from video and transcribe.

    Parameters added to reduce hallucination:
    - translate: if True, will attempt to translate to English (avoid for fidelity)
    - language: if provided (e.g., 'vi'), forces language for transcription
    - deterministic generation settings (do_sample=False, temperature=0.0)
    - chunk_length_s/stride_length_s: chunking to keep generation focused
    """
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

    audio_path = extract_audio(video_path)
    try:
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        torch_dtype = torch.float16 if device == "cuda" else torch.float32

        print(f"Loading model {model_id} on {device}...", file=sys.stderr, flush=True)

        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            model_id,
            torch_dtype=torch_dtype,
            device_map=device,
        )
        processor = AutoProcessor.from_pretrained(model_id)

        # Generation settings favoring fidelity and determinism
        generate_kwargs = {
            "do_sample": False,
            "temperature": 0.0,
            "no_repeat_ngram_size": no_repeat_ngram_size,
            "max_new_tokens": max_new_tokens,
        }

        # Build pipeline with explicit generation kwargs and chunking where supported.
        pipe = pipeline(
            "automatic-speech-recognition",
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            device=device,
        )

        transcribe_call_kwargs = {
            "return_timestamps": True,
            # Whisper-style models often support chunking params in the pipeline call
            "chunk_length_s": chunk_length_s,
            "stride_length_s": stride_length_s,
            # reduce hallucination by providing deterministic generation options
            "generate_kwargs": generate_kwargs,
        }
        if language:
            transcribe_call_kwargs["language"] = language
        # If translate True, some models will translate into English; default is transcription in source language
        if translate:
            transcribe_call_kwargs["task"] = "translate"
        else:
            transcribe_call_kwargs["task"] = "transcribe"

        print("Transcribing video (fidelity-first settings)...", file=sys.stderr, flush=True)
        # Call pipeline; many ASR pipelines accept these kwargs — if not supported, pipeline will ignore extras.
        result = pipe(audio_path, **transcribe_call_kwargs)

        # Basic post-check: if pipeline returned a single string without timestamps, wrap it
        if isinstance(result, str):
            return {"text": result}

        return result
    finally:
        import os
        try:
            os.unlink(audio_path)
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Transcribe audio from camera video")
    parser.add_argument("--video", required=True, help="Path to input MP4 video")
    parser.add_argument("--output", default="outputs/transcription.txt", help="Output text file")
    parser.add_argument("--model", default="openai/whisper-base", help="Hugging Face Whisper model")
    parser.add_argument("--device", default=None, choices=["cuda", "cpu"], help="Device to use")
    args = parser.parse_args()

    video_path = Path(args.video)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Transcribing: {video_path}", file=sys.stderr, flush=True)
    result = transcribe_video(str(video_path), model_id=args.model, device=args.device)

    text = result.get("text", "")
    if isinstance(result.get("chunks"), list):
        segments_info = []
        for chunk in result["chunks"]:
            ts = chunk.get("timestamp")
            if ts and len(ts) >= 2:
                start = ts[0] if ts[0] is not None else 0
                end = ts[1] if ts[1] is not None else 0
            else:
                start, end = 0, 0
            segments_info.append(f"[{start:.2f}s - {end:.2f}s] {chunk['text']}")
        text = "\n".join(segments_info)

    output_path.write_text(text, encoding="utf-8")
    print(f"Transcription saved to: {output_path}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()