import argparse
import gc
import json
import queue
import sys
import threading
from pathlib import Path

from tqdm import tqdm

from src.model_runner import CosmosVideoAnalyzer
from src.performance import configure_torch_runtime, get_profile, profile_names
from src.result_utils import contains_cjk, normalize_segment, replace_cjk_content, safe_json_loads, salvage_segment_from_text
from src.summary_utils import build_video_summary, save_video_summary
from src.vector_store import (
    DEFAULT_DB_DIR,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_TABLE_NAME,
    index_result_file,
)
from src.video_utils import (
    build_direct_chunk_manifest,
    build_video_id,
    get_video_info,
    iter_video_chunks,
    prepare_video_chunks,
    seconds_to_hhmmss,
)


def parse_args():
    parser = argparse.ArgumentParser(description="Cosmos/Cosmos-Reason2 video timeline analyzer")
    parser.add_argument("--video", required=True, help="Path to input MP4 video")
    parser.add_argument("--model", default="nvidia/Cosmos-Reason2-2B", help="Hugging Face model id or local model path")
    parser.add_argument("--output", default="outputs/result.json", help="Output JSON path")
    parser.add_argument("--hardware-profile", default="rtx5070ti_16gb", choices=profile_names(), help="Inference tuning profile")
    parser.add_argument("--chunk-seconds", type=int, default=None, help="Video chunk length in seconds")
    parser.add_argument("--sample-fps", type=float, default=None, help="Frame sampling FPS per chunk")
    parser.add_argument("--chunks-dir", default="outputs/chunks", help="Directory where ffmpeg chunk files are stored")
    parser.add_argument("--summaries-dir", default="outputs/summaries", help="Directory where video summaries are stored")
    parser.add_argument("--force-rechunk", action="store_true", help="Recreate ffmpeg chunk files even if a manifest exists")
    parser.add_argument("--chunk-encoder", default=None, choices=["auto", "copy", "nvenc", "cpu"], help="ffmpeg encoder for chunk files")
    parser.add_argument("--direct-sampling", action="store_true", help="Sample frames from the source video without creating chunk MP4 files")
    parser.add_argument("--max-image-side", type=int, default=None, help="Downscale sampled frames so their longest side does not exceed this value")
    parser.add_argument("--max-new-tokens", type=int, default=None, help="Max generated tokens per chunk")
    parser.add_argument("--model-backend", default="vllm", choices=["vllm", "transformers"], help="Model inference backend")
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.77, help="vLLM GPU memory utilization cap")
    parser.add_argument("--max-model-len", type=int, default=52224, help="vLLM max model length")
    parser.add_argument("--vllm-batch-size", type=int, default=2, help="Number of video chunks to send per vLLM batch")
    parser.add_argument("--device-map", default="auto", help="Transformers device_map")
    parser.add_argument("--dtype", default=None, choices=["auto", "float16", "bfloat16", "float32"], help="Torch dtype")
    parser.add_argument("--attn-implementation", default=None, choices=["auto", "sdpa", "flash_attention_2", "eager"], help="Transformers attention implementation")
    parser.add_argument("--cleanup-every", type=int, default=None, help="Run Python/CUDA cleanup every N chunks")
    parser.add_argument("--prefetch-chunks", type=int, default=2, help="Prepare this many upcoming chunks on CPU while GPU is generating")
    parser.add_argument("--skip-vector-index", action="store_true", help="Do not index result segments into LanceDB")
    parser.add_argument("--vector-db", default=str(DEFAULT_DB_DIR), help="LanceDB directory")
    parser.add_argument("--vector-table", default=DEFAULT_TABLE_NAME, help="LanceDB table name")
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL, help="SentenceTransformer embedding model")
    return parser.parse_args()


def main():
    args = parse_args()
    args = apply_profile_defaults(args)
    configure_torch_runtime()

    video_path = Path(args.video)
    output_path = Path(args.output)
    chunks_root = Path(args.chunks_dir)
    summaries_dir = Path(args.summaries_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    info = get_video_info(video_path)
    video_id = build_video_id(video_path)
    if args.direct_sampling:
        chunk_manifest = build_direct_chunk_manifest(video_path, args.chunk_seconds)
        print(
            f"Preparing video chunks: {len(chunk_manifest)}/{len(chunk_manifest)}",
            file=sys.stderr,
            flush=True,
        )
    else:
        chunk_manifest = prepare_video_chunks(
            video_path=video_path,
            chunk_seconds=args.chunk_seconds,
            chunks_root=chunks_root,
            overwrite=args.force_rechunk,
            encoder=args.chunk_encoder,
            progress_callback=lambda completed, total: print(
                f"Preparing video chunks: {completed}/{total}", file=sys.stderr, flush=True
            ),
        )
    print(f"Prepared {len(chunk_manifest)} segment(s) for analysis.", file=sys.stderr, flush=True)

    analyzer = None
    try:
        analyzer = CosmosVideoAnalyzer(
            model_id=args.model,
            max_new_tokens=args.max_new_tokens,
            device_map=args.device_map,
            dtype=args.dtype,
            attn_implementation=args.attn_implementation,
            backend=args.model_backend,
            gpu_memory_utilization=args.gpu_memory_utilization,
            max_model_len=args.max_model_len,
        )

        segments = []

        chunk_iter = iter_video_chunks(
            video_path=video_path,
            chunk_seconds=args.chunk_seconds,
            sample_fps=args.sample_fps,
            chunks_root=chunks_root,
            overwrite=False,
            encoder=args.chunk_encoder,
            direct_sampling=args.direct_sampling,
            max_image_side=args.max_image_side,
        )
        chunk_iter = prefetch_chunks(chunk_iter, max_prefetch=args.prefetch_chunks)
        batch_size = max(1, int(args.vllm_batch_size if args.model_backend == "vllm" else 1))
        pending_chunks = []
        with tqdm(total=len(chunk_manifest), desc="Analyzing video chunks", disable=not sys.stderr.isatty()) as progress:
            for chunk in chunk_iter:
                pending_chunks.append(chunk)
                if len(pending_chunks) < batch_size:
                    continue

                processed = _process_chunk_batch(
                    analyzer=analyzer,
                    chunks=pending_chunks,
                    video_path=video_path,
                    video_id=video_id,
                    output_path=output_path,
                    info=info,
                    args=args,
                    chunks_root=chunks_root,
                    existing_segments=segments,
                    total_chunks=len(chunk_manifest),
                )
                segments.extend(processed)
                progress.update(len(pending_chunks))
                pending_chunks = []
                del processed

                if args.cleanup_every > 0 and len(segments) % args.cleanup_every == 0:
                    _cleanup_memory()

            if pending_chunks:
                processed = _process_chunk_batch(
                    analyzer=analyzer,
                    chunks=pending_chunks,
                    video_path=video_path,
                    video_id=video_id,
                    output_path=output_path,
                    info=info,
                    args=args,
                    chunks_root=chunks_root,
                    existing_segments=segments,
                    total_chunks=len(chunk_manifest),
                )
                segments.extend(processed)
                progress.update(len(pending_chunks))
                pending_chunks = []
                del processed

        final_result = build_result(
            video_path=video_path,
            video_id=video_id,
            info=info,
            model=args.model,
            chunk_seconds=args.chunk_seconds,
            sample_fps=args.sample_fps,
            chunks_dir=chunks_root / video_id,
            segments=segments,
            final=True,
            runtime=build_runtime_info(args),
        )
        final_result["video_summary"] = build_video_summary(final_result)
        final_result["summary_path"] = str(save_video_summary(final_result["video_summary"], summaries_dir))
        _write_json(output_path, final_result)
    finally:
        if analyzer is not None:
            analyzer.close()
        analyzer = None
        _cleanup_memory(aggressive=True)

    if not args.skip_vector_index:
        final_result["vector_index"] = _index_vectors(
            output_path=output_path,
            db_dir=Path(args.vector_db),
            table_name=args.vector_table,
            embedding_model=args.embedding_model,
        )
        _write_json(output_path, final_result)

    print(f"Done. Result saved to: {output_path}", file=sys.stderr, flush=True)


def apply_profile_defaults(args):
    profile = get_profile(args.hardware_profile)
    if args.chunk_seconds is None:
        args.chunk_seconds = profile.chunk_seconds
    if args.sample_fps is None:
        args.sample_fps = profile.sample_fps
    if args.max_new_tokens is None:
        args.max_new_tokens = profile.max_new_tokens
    if args.dtype is None:
        args.dtype = profile.dtype
    if args.attn_implementation is None:
        args.attn_implementation = profile.attn_implementation
    if args.cleanup_every is None:
        args.cleanup_every = profile.cleanup_every
    if args.chunk_encoder is None:
        args.chunk_encoder = profile.chunk_encoder
    return args


def _process_chunk_batch(
    analyzer: CosmosVideoAnalyzer,
    chunks: list,
    video_path: Path,
    video_id: str,
    output_path: Path,
    info: dict,
    args,
    chunks_root: Path,
    existing_segments: list,
    total_chunks: int,
) -> list:
    chunk_inputs = []
    labels = []
    for chunk in chunks:
        start_label = seconds_to_hhmmss(chunk.start_seconds, mode="floor")
        end_label = seconds_to_hhmmss(chunk.end_seconds, mode="ceil")
        labels.append((start_label, end_label))
        chunk_inputs.append(
            {
                "frames": chunk.frames,
                "start_time": start_label,
                "end_time": end_label,
            }
        )

    if len(chunk_inputs) == 1:
        raw_texts = [
            analyzer.generate_description(
                frames=chunk_inputs[0]["frames"],
                start_time=chunk_inputs[0]["start_time"],
                end_time=chunk_inputs[0]["end_time"],
            )
        ]
    else:
        raw_texts = analyzer.generate_descriptions(chunk_inputs)

    new_segments = []
    for chunk, raw_text, (start_label, end_label) in zip(chunks, raw_texts, labels):
        if contains_cjk(raw_text):
            print(
                f"Non-Vietnamese output detected at {start_label}; retrying in Vietnamese.",
                file=sys.stderr,
                flush=True,
            )
            raw_text = analyzer.generate_description(
                frames=chunk.frames,
                start_time=start_label,
                end_time=end_label,
                force_vietnamese=True,
            )
        parsed = safe_json_loads(raw_text)
        if parsed is None:
            parsed = salvage_segment_from_text(raw_text, start_label, end_label)
        if contains_cjk(parsed):
            parsed = replace_cjk_content(parsed, start_label, end_label)

        segment = normalize_segment(parsed, start_label, end_label)
        segment.update(
            {
                "video_id": video_id,
                "video_file": str(video_path),
                "chunk_index": chunk.index,
                "chunk_path": str(chunk.path) if chunk.path is not None else "",
                "start_seconds": float(chunk.start_seconds),
                "end_seconds": float(chunk.end_seconds),
                "duration_seconds": float(chunk.end_seconds - chunk.start_seconds),
            }
        )
        new_segments.append(segment)

        partial_segments = [*existing_segments, *new_segments]
        partial_result = build_result(
            video_path=video_path,
            video_id=video_id,
            info=info,
            model=args.model,
            chunk_seconds=args.chunk_seconds,
            sample_fps=args.sample_fps,
            chunks_dir=chunks_root / video_id,
            segments=partial_segments,
            final=False,
            runtime=build_runtime_info(args),
        )
        _write_json(output_path, partial_result)

        print(f"Saved segment {len(partial_segments)}/{total_chunks}: {start_label} -> {end_label}", file=sys.stderr, flush=True)

        try:
            del parsed, segment, partial_segments, partial_result
        except Exception:
            pass

    for chunk in chunks:
        try:
            chunk.frames.clear()
        except Exception:
            pass

    try:
        del chunk_inputs, labels, raw_texts
    except Exception:
        pass

    return new_segments


def build_result(
    video_path: Path,
    video_id: str,
    info: dict,
    model: str,
    chunk_seconds: int,
    sample_fps: float,
    chunks_dir: Path,
    segments: list,
    final: bool,
    runtime: dict,
) -> dict:
    result = {
        "video_id": video_id,
        "video_file": str(video_path),
        "duration_seconds": info["duration_seconds"],
        "duration": seconds_to_hhmmss(info["duration_seconds"]),
        "fps": info["fps"],
        "width": info["width"],
        "height": info["height"],
        "model": model,
        "chunk_seconds": chunk_seconds,
        "sample_fps": sample_fps,
        "chunks_dir": str(chunks_dir),
        "runtime": runtime,
        "segments": segments,
    }
    if final:
        result["final_assessment"] = build_final_assessment(segments)
    return result


def build_runtime_info(args) -> dict:
    return {
        "hardware_profile": args.hardware_profile,
        "dtype": args.dtype,
        "attn_implementation": args.attn_implementation,
        "chunk_encoder": args.chunk_encoder,
        "cleanup_every": args.cleanup_every,
        "device_map": args.device_map,
        "model_backend": args.model_backend,
        "gpu_memory_utilization": args.gpu_memory_utilization,
        "max_model_len": args.max_model_len,
        "vllm_batch_size": args.vllm_batch_size,
        "direct_sampling": args.direct_sampling,
        "max_image_side": args.max_image_side,
        "prefetch_chunks": args.prefetch_chunks,
    }


def prefetch_chunks(chunk_iter, max_prefetch: int = 2):
    if max_prefetch <= 0:
        yield from chunk_iter
        return

    item_queue: queue.Queue = queue.Queue(maxsize=max_prefetch)
    sentinel = object()

    def worker() -> None:
        try:
            for item in chunk_iter:
                item_queue.put((item, None))
        except BaseException as exc:
            item_queue.put((None, exc))
        finally:
            item_queue.put((sentinel, None))

    thread = threading.Thread(target=worker, name="video-chunk-prefetch", daemon=True)
    thread.start()

    while True:
        item, exc = item_queue.get()
        if exc is not None:
            raise exc
        if item is sentinel:
            break
        yield item


def build_final_assessment(segments):
    abnormal_segments = [s for s in segments if s.get("abnormal") is True]

    if not abnormal_segments:
        return {
            "is_video_safe": True,
            "reason": "No abnormal events were detected in the analyzed segments.",
            "recommended_action": "no action needed",
        }

    high_risk = [s for s in abnormal_segments if s.get("risk_level") == "high"]
    if high_risk:
        return {
            "is_video_safe": False,
            "reason": f"{len(abnormal_segments)} abnormal segment(s) detected, including high-risk event(s).",
            "recommended_action": "review high-risk timestamps manually",
        }

    return {
        "is_video_safe": False,
        "reason": f"{len(abnormal_segments)} abnormal segment(s) detected.",
        "recommended_action": "review abnormal timestamps manually",
    }


def _fallback_segment(raw_text: str, start_label: str, end_label: str) -> dict:
    return {
        "start": start_label,
        "end": end_label,
        "description": raw_text.strip(),
        "people_count": "unknown",
        "phone_detected": False,
        "crowd_detected": False,
        "objects": [],
        "actions": [],
        "scene_changes": "unknown",
        "abnormal": False,
        "abnormal_type": "none",
        "risk_level": "none",
        "important_event": {
            "has_event": False,
            "event": "none",
            "timestamp": "none",
        },
        "confidence": 0.0,
        "raw_model_output": raw_text,
    }


def _index_vectors(
    output_path: Path,
    db_dir: Path,
    table_name: str,
    embedding_model: str,
) -> dict:
    try:
        index_info = index_result_file(
            result_path=output_path,
            db_dir=db_dir,
            table_name=table_name,
            embedding_model=embedding_model,
        )
        print(f"Vector index saved to: {db_dir} / {table_name}", file=sys.stderr, flush=True)
        return index_info
    except Exception as exc:
        message = f"Vector index failed: {exc}"
        print(message, file=sys.stderr, flush=True)
        return {
            "indexed": False,
            "db_dir": str(db_dir),
            "table": table_name,
            "embedding_model": embedding_model,
            "error": str(exc),
        }


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _cleanup_memory(aggressive: bool = False) -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            if aggressive:
                torch.cuda.ipc_collect()
    except Exception:
        pass


if __name__ == "__main__":
    main()
