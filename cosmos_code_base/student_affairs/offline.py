"""Offline video runner for validating the Student Affairs CV pipeline.

Run with a recorded pilot video before connecting the camera Live service:

    python -m student_affairs.offline input.mp4 configs/cameras/student_affairs_pilot.yaml \
        --output outputs/pilot_overlay.mp4
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
from PIL import Image

from .config import CameraProfile, load_camera_profile
from .detector import PersonCandidate, StudentAffairsDetector
from .rules import StudentAffairsRules, TrackObservation
from .tracker import CameraPersonTracker, TrackedPerson
from .zones import point_in_polygon


class CandidateDetector(Protocol):
    def detect(self, image: Image.Image) -> list[PersonCandidate]: ...


@dataclass(frozen=True)
class FrameAnalysis:
    tracks: list[TrackedPerson]
    event: dict


class StudentAffairsPipeline:
    """Detector, per-camera tracker and rule engine composed for one profile."""

    def __init__(self, profile: CameraProfile, detector: CandidateDetector | None = None, tracker: CameraPersonTracker | None = None) -> None:
        self.profile = profile
        self.detector = detector or StudentAffairsDetector()
        self.tracker = tracker or CameraPersonTracker()
        self.rules = StudentAffairsRules(profile)

    def process(self, image: Image.Image, captured_at: datetime) -> FrameAnalysis:
        candidates = self.detector.detect(image)
        tracks = self.tracker.update(captured_at, candidates, image.size)
        observations = [TrackObservation(track.track_id, track.footpoint, track.yellow_score) for track in tracks]
        return FrameAnalysis(tracks, self.rules.update(captured_at, observations))


def _polygon_pixels(polygon: tuple[tuple[float, float], ...], width: int, height: int) -> np.ndarray:
    return np.asarray([(round(x * width), round(y * height)) for x, y in polygon], dtype=np.int32)


def zone_for_track(track: TrackedPerson, profile: CameraProfile) -> str:
    for desk in profile.desks:
        if point_in_polygon(track.footpoint, desk.polygon):
            return desk.id
    if point_in_polygon(track.footpoint, profile.waiting):
        return "waiting"
    if point_in_polygon(track.footpoint, profile.entrance):
        return "entrance"
    return "outside_zones"


def draw_overlay(frame: np.ndarray, analysis: FrameAnalysis, profile: CameraProfile) -> np.ndarray:
    """Return a BGR frame annotated with configured zones and visible track IDs."""
    annotated = frame.copy()
    height, width = annotated.shape[:2]
    for name, polygon, colour in [("entrance", profile.entrance, (255, 160, 0)), ("waiting", profile.waiting, (0, 180, 255))]:
        points = _polygon_pixels(polygon, width, height)
        cv2.polylines(annotated, [points], True, colour, 2)
        cv2.putText(annotated, name, tuple(points[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.55, colour, 2, cv2.LINE_AA)
    for desk in profile.desks:
        points = _polygon_pixels(desk.polygon, width, height)
        cv2.polylines(annotated, [points], True, (0, 255, 0), 2)
        cv2.putText(annotated, desk.id, tuple(points[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2, cv2.LINE_AA)
    for track in analysis.tracks:
        x1, y1, x2, y2 = track.bbox
        colour = (0, 255, 0) if track.yellow_score >= 0.55 else (230, 230, 230)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), colour, 2)
        label = f"#{track.track_id} {zone_for_track(track, profile)} y={track.yellow_score:.2f}"
        cv2.putText(annotated, label, (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 2, cv2.LINE_AA)
    status = f"scene={analysis.event['scene_status']} alerts={len(analysis.event['alerts'])}"
    cv2.putText(annotated, status, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2, cv2.LINE_AA)
    return annotated


def run_video(input_path: str | Path, profile: CameraProfile, output_path: str | Path, *, log_path: str | Path | None = None, sample_interval_seconds: float | None = None, start_at: datetime | None = None) -> int:
    """Process a video and return the number of sampled frames analysed."""
    source = cv2.VideoCapture(str(input_path))
    if not source.isOpened():
        raise ValueError(f"cannot open video: {input_path}")
    fps = source.get(cv2.CAP_PROP_FPS) or 0.0
    width, height = int(source.get(cv2.CAP_PROP_FRAME_WIDTH)), int(source.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if fps <= 0 or width <= 0 or height <= 0:
        source.release()
        raise ValueError("video has invalid FPS or dimensions")
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(target), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        source.release()
        raise ValueError(f"cannot create output video: {target}")
    interval = sample_interval_seconds or profile.thresholds.frame_interval_seconds
    if interval <= 0:
        raise ValueError("sample_interval_seconds must be positive")
    current_time = start_at or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        raise ValueError("start_at must include timezone information")
    pipeline = StudentAffairsPipeline(profile)
    logs = Path(log_path).open("w", encoding="utf-8") if log_path else None
    previous_analysis: FrameAnalysis | None = None
    next_sample_at = 0.0
    analysed = 0
    frame_index = 0
    try:
        while True:
            ok, frame = source.read()
            if not ok:
                break
            seconds = frame_index / fps
            if seconds + 1e-9 >= next_sample_at:
                image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                previous_analysis = pipeline.process(image, current_time + timedelta(seconds=seconds))
                if logs:
                    logs.write(json.dumps(previous_analysis.event, ensure_ascii=False) + "\n")
                analysed += 1
                next_sample_at += interval
            writer.write(draw_overlay(frame, previous_analysis, profile) if previous_analysis else frame)
            frame_index += 1
    finally:
        source.release()
        writer.release()
        if logs:
            logs.close()
    return analysed


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Student Affairs tracker/rule overlay from a recorded video.")
    parser.add_argument("input", help="recorded input video")
    parser.add_argument("profile", help="camera profile YAML")
    parser.add_argument("--output", required=True, help="output MP4 with overlays")
    parser.add_argument("--log", help="optional JSONL file for sampled rule-engine events")
    parser.add_argument("--sample-seconds", type=float, help="detector/tracker sampling interval; defaults to the profile")
    args = parser.parse_args()
    frames = run_video(args.input, load_camera_profile(args.profile), args.output, log_path=args.log, sample_interval_seconds=args.sample_seconds)
    print(f"Created {args.output}; analysed {frames} sampled frames.")


if __name__ == "__main__":
    main()
