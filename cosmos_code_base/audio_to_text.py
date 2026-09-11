import argparse
import os
import subprocess
import sys
from pathlib import Path

import torch


def extract_audio(video_path: str, audio_path: str = None, sample_rate: int = 16000) -> str:
    """Extract mono PCM WAV from video file at specified sample rate."""
    if audio_path is None:
        temp_dir = os.path.join(os.path.dirname(video_path), "temp_audio")
        os.makedirs(temp_dir, exist_ok=True)
        audio_path = os.path.join(temp_dir, "audio_extracted.wav")

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le",
        "-ar", str(sample_rate), "-ac", "1",
        "-f", "wav", audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed: {result.stderr}")
    return audio_path


def transcribe_video(
    video_path: str,
    model_id: str = "whisper-large-v3-turbo",
    device: str = None,
    translate: bool = False,
    language: str | None = "vi",
    max_new_tokens: int = 512,
    chunk_length_s: int = 30,
    stride_length_s: int = 5,
    no_repeat_ngram_size: int = 3,
    use_deepfilter: bool = True,
) -> dict:
    """Extract audio from video and transcribe.

    Integrates DeepFilterNet3 for noise reduction and Faster-Whisper Large-v3
    for accurate, low-hallucination Vietnamese speech-to-text.
    """
    # 1. Check if we should use the new DeepFilterNet + Faster-Whisper pipeline
    is_whisper = any(k in model_id.lower() for k in ["whisper", "large-v3", "base", "small", "medium", "tiny"])
    has_custom_hf = "vinai/" in model_id or "/" in model_id and not any(k in model_id.lower() for k in ["openai/whisper", "systran/faster-whisper", "mobiuslabsgmbh/"])

    if is_whisper and not has_custom_hf:
        try:
            from audio_enhancer import full_audio_pipeline
            # When using DeepFilterNet, extract at 48000 Hz for optimal filtering
            sr = 48000 if use_deepfilter else 16000
            extracted_path = extract_audio(video_path, sample_rate=sr)
            try:
                return full_audio_pipeline(
                    extracted_path,
                    use_deepfilter=use_deepfilter,
                    model_name=model_id,
                    language=language or "vi",
                )
            finally:
                if os.path.exists(extracted_path):
                    try:
                        os.unlink(extracted_path)
                    except OSError:
                        pass
        except Exception as exc:
            print(f"Faster-Whisper/DeepFilter pipeline notice: {exc}, falling back to transformers pipeline...", file=sys.stderr)

    # 2. Fallback to HuggingFace Transformers pipeline
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

    extracted_path = extract_audio(video_path, sample_rate=16000)
    try:
        if use_deepfilter:
            try:
                from audio_enhancer import enhance_audio_file
                cleaned_path = enhance_audio_file(extracted_path, target_sr=16000)
                os.unlink(extracted_path)
                extracted_path = cleaned_path
            except Exception as df_err:
                print(f"DeepFilterNet fallback notice: {df_err}", file=sys.stderr)

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

        generate_kwargs = {
            "do_sample": False,
            "temperature": 0.0,
            "no_repeat_ngram_size": no_repeat_ngram_size,
            "max_new_tokens": max_new_tokens,
        }

        pipe = pipeline(
            "automatic-speech-recognition",
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            device=device,
        )

        transcribe_call_kwargs = {
            "return_timestamps": True,
            "chunk_length_s": chunk_length_s,
            "stride_length_s": stride_length_s,
            "generate_kwargs": generate_kwargs,
        }
        if language:
            transcribe_call_kwargs["language"] = language
        if translate:
            transcribe_call_kwargs["task"] = "translate"
        else:
            transcribe_call_kwargs["task"] = "transcribe"

        print("Transcribing video (fidelity-first settings)...", file=sys.stderr, flush=True)
        result = pipe(extracted_path, **transcribe_call_kwargs)

        if isinstance(result, str):
            return {"text": result}

        return result
    finally:
        if os.path.exists(extracted_path):
            try:
                os.unlink(extracted_path)
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="Transcribe audio from camera video using DeepFilterNet & Whisper Large-v3")
    parser.add_argument("--video", required=True, help="Path to input MP4 video")
    parser.add_argument("--output", default="outputs/transcription.txt", help="Output text file")
    parser.add_argument("--model", default="whisper-large-v3-turbo", help="Whisper model (e.g. whisper-large-v3-turbo, whisper-large-v3)")
    parser.add_argument("--device", default=None, choices=["cuda", "cpu"], help="Device to use")
    parser.add_argument("--no-deepfilter", action="store_true", help="Disable DeepFilterNet noise reduction")
    args = parser.parse_args()

    video_path = Path(args.video)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Transcribing: {video_path}", file=sys.stderr, flush=True)
    result = transcribe_video(
        str(video_path),
        model_id=args.model,
        device=args.device,
        use_deepfilter=not args.no_deepfilter,
    )

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