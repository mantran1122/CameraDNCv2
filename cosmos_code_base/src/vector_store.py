import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from src.result_utils import clean_text, segment_search_text


DEFAULT_DB_DIR = Path("outputs/lancedb")
DEFAULT_TABLE_NAME = "video_segments"
DEFAULT_SUMMARY_TABLE_NAME = "video_summaries"
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
SCHEMA_VERSION = 1

_db_cache: Dict[str, Any] = {}


def index_result_file(
    result_path: Path,
    db_dir: Path = DEFAULT_DB_DIR,
    table_name: str = DEFAULT_TABLE_NAME,
    summary_table_name: str = DEFAULT_SUMMARY_TABLE_NAME,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
) -> Dict[str, Any]:
    data = json.loads(result_path.read_text(encoding="utf-8"))
    metadata = {
        "video_id": data.get("video_id", ""),
        "video_file": data.get("video_file", ""),
        "result_path": str(result_path),
    }
    segment_info = index_segments(
        segments=data.get("segments", []),
        metadata=metadata,
        db_dir=db_dir,
        table_name=table_name,
        embedding_model=embedding_model,
    )
    summary_info = index_video_summary(
        summary=data.get("video_summary", {}),
        metadata=metadata,
        db_dir=db_dir,
        table_name=summary_table_name,
        embedding_model=embedding_model,
    )
    return {
        **segment_info,
        "segment_table": table_name,
        "summary_table": summary_table_name,
        "summary_index": summary_info,
    }


def index_segments(
    segments: Iterable[Dict[str, Any]],
    metadata: Dict[str, Any],
    db_dir: Path = DEFAULT_DB_DIR,
    table_name: str = DEFAULT_TABLE_NAME,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
) -> Dict[str, Any]:
    segment_list = [segment for segment in segments if isinstance(segment, dict)]
    if not segment_list:
        return {
            "indexed": False,
            "reason": "No segments to index",
            "db_dir": str(db_dir),
            "table": table_name,
            "count": 0,
        }

    texts = [segment_search_text(segment) for segment in segment_list]
    vectors = embed_texts(texts, embedding_model)
    rows = [
        _segment_to_row(segment, text, vector, metadata, embedding_model)
        for segment, text, vector in zip(segment_list, texts, vectors)
    ]

    db_dir.mkdir(parents=True, exist_ok=True)
    db = _connect(db_dir)

    if table_name in db.table_names():
        table = db.open_table(table_name)
        video_id = clean_text(metadata.get("video_id", ""))
        if video_id:
            try:
                table.delete(f"video_id = '{_escape_sql_value(video_id)}'")
            except Exception:
                pass
        try:
            table.add(rows)
        except Exception:
            db.drop_table(table_name)
            db.create_table(table_name, data=rows)
    else:
        db.create_table(table_name, data=rows)

    return {
        "indexed": True,
        "db_dir": str(db_dir),
        "table": table_name,
        "count": len(rows),
        "embedding_model": embedding_model,
    }


def search_segments(
    query: str,
    db_dir: Path = DEFAULT_DB_DIR,
    table_name: str = DEFAULT_TABLE_NAME,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    video_id: Optional[str] = None,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    cleaned_query = build_natural_language_query(query)
    if not cleaned_query:
        return []

    db = _connect(db_dir)
    if table_name not in db.table_names():
        raise RuntimeError(f"LanceDB table not found: {db_dir}/{table_name}")

    query_vector = embed_texts([cleaned_query], embedding_model)[0]
    table = db.open_table(table_name)
    search = table.search(query_vector)
    if video_id:
        filter_expr = f"video_id = '{_escape_sql_value(video_id)}'"
        try:
            search = search.where(filter_expr, prefilter=True)
        except TypeError:
            search = search.where(filter_expr)

    items = search.limit(max(1, int(limit))).to_list()
    return [_row_to_match(item) for item in items]


def search_segments_hybrid(
    query: str,
    db_dir: Path = DEFAULT_DB_DIR,
    table_name: str = DEFAULT_TABLE_NAME,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    video_id: Optional[str] = None,
    limit: int = 8,
    candidate_limit: int = 40,
    vector_weight: float = 0.7,
) -> List[Dict[str, Any]]:
    candidates = search_segments(
        query=query,
        db_dir=db_dir,
        table_name=table_name,
        embedding_model=embedding_model,
        video_id=video_id,
        limit=max(int(limit), int(candidate_limit)),
    )
    if not candidates:
        return []

    cleaned_query = clean_text(query).lower()
    enriched: List[Dict[str, Any]] = []
    for item in candidates:
        metadata_score = _metadata_match_score(cleaned_query, item)
        vector_score = _safe_float(item.get("score"))
        hybrid_score = (vector_weight * vector_score) + ((1.0 - vector_weight) * metadata_score)
        merged = dict(item)
        merged["metadata_score"] = metadata_score
        merged["hybrid_score"] = hybrid_score
        enriched.append(merged)

    enriched.sort(key=lambda x: (x.get("hybrid_score", 0.0), x.get("score", 0.0)), reverse=True)
    return enriched[: max(1, int(limit))]


def search_video(
    query: str,
    db_dir: Path = DEFAULT_DB_DIR,
    segment_table_name: str = DEFAULT_TABLE_NAME,
    summary_table_name: str = DEFAULT_SUMMARY_TABLE_NAME,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    video_id: Optional[str] = None,
    limit: int = 8,
) -> Dict[str, Any]:
    return {
        "query": clean_text(query),
        "summary_matches": search_video_summaries(
            query=query,
            db_dir=db_dir,
            table_name=summary_table_name,
            embedding_model=embedding_model,
            video_id=video_id,
            limit=1,
        ),
        "segment_matches": search_segments_hybrid(
            query=query,
            db_dir=db_dir,
            table_name=segment_table_name,
            embedding_model=embedding_model,
            video_id=video_id,
            limit=limit,
        ),
    }


def build_natural_language_query(query: str) -> str:
    cleaned = clean_text(query)
    if not cleaned:
        return ""

    lowered = cleaned.lower()
    hints = [
        "Tìm các đoạn video phù hợp với câu hỏi bằng ngữ nghĩa tự nhiên.",
        "Ưu tiên mô tả, hành động, đối tượng, sự kiện, số người, bất thường và thời gian.",
    ]
    if any(term in lowered for term in ["tóm tắt", "ý nghĩa", "nói gì", "nội dung", "đại khái", "tổng quan"]):
        hints.append("Câu hỏi đang hỏi về tóm tắt, ý nghĩa tổng quát và nội dung chính của video.")
    if any(term in lowered for term in ["đám đông", "tụ tập", "nhiều người", "hơn hai", "3 người", "ba người"]):
        hints.append("Liên quan đến crowding, tụ tập, nhiều hơn hai người, ba người trong khung hình.")
    if any(term in lowered for term in ["điện thoại", "phone", "mobile", "gọi điện", "chụp ảnh", "quay video"]):
        hints.append("Liên quan đến điện thoại, cầm điện thoại, nhìn điện thoại, chụp ảnh hoặc quay video.")
    return clean_text(f"Câu hỏi: {cleaned}. {' '.join(hints)}")


def index_video_summary(
    summary: Dict[str, Any],
    metadata: Dict[str, Any],
    db_dir: Path = DEFAULT_DB_DIR,
    table_name: str = DEFAULT_SUMMARY_TABLE_NAME,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
) -> Dict[str, Any]:
    if not isinstance(summary, dict) or not summary:
        return {
            "indexed": False,
            "reason": "No video summary to index",
            "db_dir": str(db_dir),
            "table": table_name,
            "count": 0,
        }

    search_text = _summary_search_text(summary)
    vector = embed_texts([search_text], embedding_model)[0]
    row = _summary_to_row(summary, search_text, vector, metadata, embedding_model)

    db_dir.mkdir(parents=True, exist_ok=True)
    db = _connect(db_dir)
    if table_name in db.table_names():
        table = db.open_table(table_name)
        video_id = clean_text(summary.get("video_id") or metadata.get("video_id", ""))
        if video_id:
            try:
                table.delete(f"video_id = '{_escape_sql_value(video_id)}'")
            except Exception:
                pass
        try:
            table.add([row])
        except Exception:
            db.drop_table(table_name)
            db.create_table(table_name, data=[row])
    else:
        db.create_table(table_name, data=[row])

    return {
        "indexed": True,
        "db_dir": str(db_dir),
        "table": table_name,
        "count": 1,
        "embedding_model": embedding_model,
    }


def search_video_summaries(
    query: str,
    db_dir: Path = DEFAULT_DB_DIR,
    table_name: str = DEFAULT_SUMMARY_TABLE_NAME,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    video_id: Optional[str] = None,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    cleaned_query = build_natural_language_query(query)
    if not cleaned_query:
        return []

    db = _connect(db_dir)
    if table_name not in db.table_names():
        return []

    query_vector = embed_texts([cleaned_query], embedding_model)[0]
    table = db.open_table(table_name)
    search = table.search(query_vector)
    if video_id:
        filter_expr = f"video_id = '{_escape_sql_value(video_id)}'"
        try:
            search = search.where(filter_expr, prefilter=True)
        except TypeError:
            search = search.where(filter_expr)

    items = search.limit(max(1, int(limit))).to_list()
    return [_summary_row_to_match(item) for item in items]


def embed_texts(texts: List[str], embedding_model: str = DEFAULT_EMBEDDING_MODEL) -> List[List[float]]:
    if not texts:
        return []
    model = _load_sentence_transformer(embedding_model)
    vectors = model.encode(
        texts,
        batch_size=16,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    return vectors.tolist()


@lru_cache(maxsize=4)
def _load_sentence_transformer(model_name: str):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency sentence-transformers. Run install_D.bat or "
            "pip install -r requirements.txt."
        ) from exc

    return SentenceTransformer(model_name, cache_folder=_embedding_cache_dir())


def _connect(db_dir: Path):
    try:
        import lancedb
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency lancedb. Run install_D.bat or pip install -r requirements.txt."
        ) from exc

    key = str(db_dir.resolve())
    if key not in _db_cache:
        _db_cache[key] = lancedb.connect(str(db_dir))
    return _db_cache[key]


def _embedding_cache_dir() -> str:
    cache_root = os.getenv("SENTENCE_TRANSFORMERS_HOME") or os.getenv("HF_HOME")
    if cache_root:
        return cache_root

    cache_dir = Path(__file__).resolve().parents[1] / "local_env" / "hf_cache" / "sentence_transformers"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return str(cache_dir)


def _segment_to_row(
    segment: Dict[str, Any],
    search_text: str,
    vector: List[float],
    metadata: Dict[str, Any],
    embedding_model: str,
) -> Dict[str, Any]:
    return {
        "vector": vector,
        "schema_version": SCHEMA_VERSION,
        "video_id": clean_text(segment.get("video_id") or metadata.get("video_id", "")),
        "video_file": clean_text(segment.get("video_file") or metadata.get("video_file", "")),
        "result_path": clean_text(metadata.get("result_path", "")),
        "chunk_index": _safe_int(segment.get("chunk_index", -1)),
        "chunk_path": clean_text(segment.get("chunk_path", "")),
        "start": clean_text(segment.get("start", "")),
        "end": clean_text(segment.get("end", "")),
        "start_seconds": _safe_float(segment.get("start_seconds", 0.0)),
        "end_seconds": _safe_float(segment.get("end_seconds", 0.0)),
        "description": clean_text(segment.get("description", "")),
        "objects_json": json.dumps(segment.get("objects", []), ensure_ascii=False),
        "actions_json": json.dumps(segment.get("actions", []), ensure_ascii=False),
        "risk_level": clean_text(segment.get("risk_level", "none")),
        "abnormal_type": clean_text(segment.get("abnormal_type", "none")),
        "abnormal": bool(segment.get("abnormal", False)),
        "phone_detected": bool(segment.get("phone_detected", False)),
        "crowd_detected": bool(segment.get("crowd_detected", False)),
        "confidence": _safe_float(segment.get("confidence", 0.0)),
        "search_text": search_text,
        "embedding_model": embedding_model,
    }


def _row_to_match(row: Dict[str, Any]) -> Dict[str, Any]:
    distance = row.get("_distance")
    score = None
    if distance is not None:
        try:
            score = max(0.0, 1.0 - min(float(distance), 2.0) / 2.0)
        except Exception:
            score = None

    return {
        "video_id": row.get("video_id", ""),
        "video_file": row.get("video_file", ""),
        "chunk_index": row.get("chunk_index", -1),
        "chunk_path": row.get("chunk_path", ""),
        "start": row.get("start", ""),
        "end": row.get("end", ""),
        "start_seconds": _safe_float(row.get("start_seconds", 0.0)),
        "end_seconds": _safe_float(row.get("end_seconds", 0.0)),
        "description": row.get("description", ""),
        "risk_level": row.get("risk_level", "none"),
        "abnormal_type": row.get("abnormal_type", "none"),
        "abnormal": bool(row.get("abnormal", False)),
        "phone_detected": bool(row.get("phone_detected", False)),
        "crowd_detected": bool(row.get("crowd_detected", False)),
        "confidence": _safe_float(row.get("confidence", 0.0)),
        "search_text": row.get("search_text", ""),
        "distance": distance,
        "score": score,
    }


def _summary_search_text(summary: Dict[str, Any]) -> str:
    if summary.get("searchable_text"):
        return clean_text(summary.get("searchable_text"))
    key_moments = " ".join(
        f"{moment.get('start')} đến {moment.get('end')}: {moment.get('description')}"
        for moment in summary.get("key_moments", [])
        if isinstance(moment, dict)
    )
    return clean_text(
        f"{summary.get('overview', '')} {summary.get('meaning', '')} "
        f"Chủ thể chính: {', '.join(summary.get('main_subjects', []))}. "
        f"Hành động chính: {', '.join(summary.get('main_actions', []))}. "
        f"Các mốc chính: {key_moments}"
    )


def _summary_to_row(
    summary: Dict[str, Any],
    search_text: str,
    vector: List[float],
    metadata: Dict[str, Any],
    embedding_model: str,
) -> Dict[str, Any]:
    return {
        "vector": vector,
        "schema_version": SCHEMA_VERSION,
        "video_id": clean_text(summary.get("video_id") or metadata.get("video_id", "")),
        "video_file": clean_text(summary.get("video_file") or metadata.get("video_file", "")),
        "result_path": clean_text(metadata.get("result_path", "")),
        "duration": clean_text(summary.get("duration", "")),
        "duration_seconds": _safe_float(summary.get("duration_seconds", 0.0)),
        "segment_count": _safe_int(summary.get("segment_count", 0)),
        "overview": clean_text(summary.get("overview", "")),
        "meaning": clean_text(summary.get("meaning", "")),
        "main_subjects_json": json.dumps(summary.get("main_subjects", []), ensure_ascii=False),
        "main_actions_json": json.dumps(summary.get("main_actions", []), ensure_ascii=False),
        "key_moments_json": json.dumps(summary.get("key_moments", []), ensure_ascii=False),
        "search_text": search_text,
        "embedding_model": embedding_model,
    }


def _summary_row_to_match(row: Dict[str, Any]) -> Dict[str, Any]:
    distance = row.get("_distance")
    score = None
    if distance is not None:
        try:
            score = max(0.0, 1.0 - min(float(distance), 2.0) / 2.0)
        except Exception:
            score = None

    return {
        "video_id": row.get("video_id", ""),
        "video_file": row.get("video_file", ""),
        "duration": row.get("duration", ""),
        "duration_seconds": _safe_float(row.get("duration_seconds", 0.0)),
        "segment_count": _safe_int(row.get("segment_count", 0)),
        "overview": row.get("overview", ""),
        "meaning": row.get("meaning", ""),
        "main_subjects": _loads_json_list(row.get("main_subjects_json", "[]")),
        "main_actions": _loads_json_list(row.get("main_actions_json", "[]")),
        "key_moments": _loads_json_list(row.get("key_moments_json", "[]")),
        "search_text": row.get("search_text", ""),
        "distance": distance,
        "score": score,
    }


def _escape_sql_value(value: str) -> str:
    return str(value).replace("'", "''")


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return -1


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _loads_json_list(value: Any) -> List[Any]:
    try:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, list) else []
    except Exception:
        return []


def _metadata_match_score(query_lower: str, row: Dict[str, Any]) -> float:
    score = 0.0
    checks = 0

    checks += 1
    if any(term in query_lower for term in ["điện thoại", "phone", "mobile", "gọi điện", "chụp ảnh", "quay video"]):
        if bool(row.get("phone_detected", False)):
            score += 1.0

    checks += 1
    if any(term in query_lower for term in ["đám đông", "tụ tập", "nhiều người", "crowd"]):
        if bool(row.get("crowd_detected", False)):
            score += 1.0

    checks += 1
    if any(term in query_lower for term in ["bất thường", "rủi ro", "nguy hiểm"]):
        if bool(row.get("abnormal", False)) or clean_text(row.get("risk_level", "")).lower() in {"medium", "high"}:
            score += 1.0

    checks += 1
    if any(term in query_lower for term in ["rủi ro cao", "high risk", "nghiêm trọng"]):
        if clean_text(row.get("risk_level", "")).lower() == "high":
            score += 1.0

    return score / max(1, checks)
