import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vector_store import DEFAULT_TABLE_NAME, index_result_file, search_segments, search_video_summaries


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run semantic search checks against the demo video result.")
    parser.add_argument("--result", default="outputs/result_demo.json", help="Analyzed result JSON")
    parser.add_argument("--cases", default="tests/demo_search_cases.json", help="Search test cases JSON")
    parser.add_argument("--db-dir", default="outputs/lancedb", help="LanceDB directory")
    parser.add_argument("--table", default=DEFAULT_TABLE_NAME, help="LanceDB table")
    parser.add_argument("--report", default="outputs/demo_search_test_report.json", help="Where to save the test report")
    parser.add_argument("--rebuild-index", action="store_true", help="Rebuild LanceDB from the result before searching")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result_path = ROOT / args.result
    cases_path = ROOT / args.cases
    db_dir = ROOT / args.db_dir
    report_path = ROOT / args.report

    result = _load_json(result_path)
    cases = _load_json(cases_path)

    failures: List[str] = []
    _validate_result(result_path, result, failures)

    if args.rebuild_index or not _result_has_index(result):
        info = index_result_file(result_path=result_path, db_dir=db_dir, table_name=args.table)
        result["vector_index"] = info

    video_id = result.get("video_id")
    report = {
        "result": str(result_path),
        "video_id": video_id,
        "summary": result.get("video_summary", {}),
        "cases": [],
    }

    _validate_video_summary(result, failures)
    summary_matches = search_video_summaries(
        query="video này nói về điều gì, ý nghĩa tổng quát là gì",
        db_dir=db_dir,
        video_id=video_id,
        limit=1,
    )
    report["summary_search"] = summary_matches
    if not summary_matches:
        failures.append("summary_search: expected at least 1 summary match")

    for case in cases:
        case_report = _run_case(case=case, db_dir=db_dir, table=args.table, video_id=video_id, failures=failures)
        report["cases"].append(case_report)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nAll demo search tests passed.")
    return 0


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_result(result_path: Path, result: Dict[str, Any], failures: List[str]) -> None:
    segments = result.get("segments", [])
    if not segments:
        failures.append(f"{result_path} has no segments")
        return

    for index, segment in enumerate(segments):
        start = segment.get("start")
        end = segment.get("end")
        start_seconds = _safe_float(segment.get("start_seconds"))
        end_seconds = _safe_float(segment.get("end_seconds"))
        chunk_path = ROOT / str(segment.get("chunk_path", ""))

        if not start or not end:
            failures.append(f"segment {index} is missing start/end")
        if end_seconds <= start_seconds:
            failures.append(f"segment {index} has invalid seconds: {start_seconds} -> {end_seconds}")
        if not chunk_path.exists():
            failures.append(f"segment {index} chunk file does not exist: {chunk_path}")


def _validate_video_summary(result: Dict[str, Any], failures: List[str]) -> None:
    summary = result.get("video_summary") or {}
    if not summary:
        failures.append("result has no video_summary")
        return
    for key in ["overview", "meaning", "key_moments", "searchable_text"]:
        if not summary.get(key):
            failures.append(f"video_summary is missing {key}")


def _result_has_index(result: Dict[str, Any]) -> bool:
    return bool((result.get("vector_index") or {}).get("indexed"))


def _run_case(
    case: Dict[str, Any],
    db_dir: Path,
    table: str,
    video_id: str,
    failures: List[str],
) -> Dict[str, Any]:
    name = case.get("name", "unnamed")
    query = case["query"]
    limit = int(case.get("limit", 5))
    min_results = int(case.get("min_results", 1))

    matches = search_segments(query=query, db_dir=db_dir, table_name=table, video_id=video_id, limit=limit)
    compact_matches = [_compact_match(match) for match in matches]

    if len(matches) < min_results:
        failures.append(f"{name}: expected at least {min_results} result(s), got {len(matches)}")

    for match_index, match in enumerate(matches):
        start_seconds = _safe_float(match.get("start_seconds"))
        end_seconds = _safe_float(match.get("end_seconds"))
        chunk_path = ROOT / str(match.get("chunk_path", ""))

        if not match.get("start") or not match.get("end"):
            failures.append(f"{name}: match {match_index} is missing start/end")
        if end_seconds <= start_seconds:
            failures.append(f"{name}: match {match_index} has invalid seconds")
        if not chunk_path.exists():
            failures.append(f"{name}: match {match_index} chunk file does not exist: {chunk_path}")

    return {
        "name": name,
        "query": query,
        "result_count": len(matches),
        "top_matches": compact_matches,
    }


def _compact_match(match: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "start": match.get("start"),
        "end": match.get("end"),
        "chunk_path": match.get("chunk_path"),
        "score": match.get("score"),
        "description": match.get("description"),
        "risk_level": match.get("risk_level"),
        "abnormal_type": match.get("abnormal_type"),
    }


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main())
