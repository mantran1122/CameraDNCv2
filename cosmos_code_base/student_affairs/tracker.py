"""Conservative, per-camera person tracking for the Student Affairs pilot.

The tracker deliberately creates a new ID when the match is ambiguous instead
of aggressively joining two people.  Its output is suitable for zone/rule
processing; it must not be used as evidence of a person's identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import hypot
from typing import Protocol

from .zones import bbox_footpoint


class PersonDetection(Protocol):
    """The minimal detector output needed by the tracker."""

    bbox: tuple[int, int, int, int]
    confidence: float
    yellow_score: float
    blue_score: float


@dataclass(frozen=True)
class TrackedPerson:
    track_id: int
    bbox: tuple[int, int, int, int]
    confidence: float
    yellow_score: float
    blue_score: float
    footpoint: tuple[float, float]


@dataclass
class _TrackState:
    track_id: int
    bbox: tuple[int, int, int, int]
    last_seen: datetime


def _iou(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> float:
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    if not intersection:
        return 0.0
    first_area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    second_area = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def _centres_close(first: tuple[int, int, int, int], second: tuple[int, int, int, int], maximum_scale: float) -> bool:
    first_centre = ((first[0] + first[2]) / 2, (first[1] + first[3]) / 2)
    second_centre = ((second[0] + second[2]) / 2, (second[1] + second[3]) / 2)
    reference_size = max(first[2] - first[0], first[3] - first[1], second[2] - second[0], second[3] - second[1])
    return reference_size > 0 and hypot(first_centre[0] - second_centre[0], first_centre[1] - second_centre[1]) <= reference_size * maximum_scale


class CameraPersonTracker:
    """One tracker instance for exactly one camera stream."""

    def __init__(self, *, min_iou: float = 0.2, max_center_distance_scale: float = 1.25, max_age_seconds: float = 3.0) -> None:
        if not 0 < min_iou <= 1:
            raise ValueError("min_iou must be in (0, 1]")
        if max_center_distance_scale <= 0 or max_age_seconds <= 0:
            raise ValueError("distance scale and max age must be positive")
        self.min_iou = min_iou
        self.max_center_distance_scale = max_center_distance_scale
        self.max_age_seconds = max_age_seconds
        self._tracks: dict[int, _TrackState] = {}
        self._next_track_id = 1
        self._last_captured_at: datetime | None = None

    def update(self, captured_at: datetime, detections: list[PersonDetection], image_size: tuple[int, int]) -> list[TrackedPerson]:
        """Associate one frame's detections and return only visible tracks."""
        if captured_at.tzinfo is None:
            raise ValueError("captured_at must include timezone information")
        if self._last_captured_at is not None and captured_at < self._last_captured_at:
            raise ValueError("captured_at must not move backwards for a camera")
        width, height = image_size
        if width <= 0 or height <= 0:
            raise ValueError("image_size must be positive")
        self._expire(captured_at)

        pairs: list[tuple[float, int, int]] = []
        for track_id, state in self._tracks.items():
            for detection_index, detection in enumerate(detections):
                overlap = _iou(state.bbox, detection.bbox)
                if overlap >= self.min_iou or _centres_close(state.bbox, detection.bbox, self.max_center_distance_scale):
                    # IoU dominates; the tiny index terms make matching deterministic.
                    pairs.append((overlap, track_id, detection_index))
        pairs.sort(key=lambda item: (-item[0], item[1], item[2]))
        matched_tracks: set[int] = set()
        matched_detections: dict[int, int] = {}
        for _overlap, track_id, detection_index in pairs:
            if track_id not in matched_tracks and detection_index not in matched_detections:
                matched_tracks.add(track_id)
                matched_detections[detection_index] = track_id

        visible: list[TrackedPerson] = []
        for detection_index, detection in enumerate(detections):
            track_id = matched_detections.get(detection_index)
            if track_id is None:
                track_id = self._next_track_id
                self._next_track_id += 1
            self._tracks[track_id] = _TrackState(track_id, detection.bbox, captured_at)
            visible.append(TrackedPerson(track_id, detection.bbox, detection.confidence, detection.yellow_score, detection.blue_score, bbox_footpoint(detection.bbox, width, height)))
        self._last_captured_at = captured_at
        return visible

    def _expire(self, captured_at: datetime) -> None:
        self._tracks = {
            track_id: state for track_id, state in self._tracks.items()
            if (captured_at - state.last_seen).total_seconds() <= self.max_age_seconds
        }


class CameraTrackerRegistry:
    """Own a separate ``CameraPersonTracker`` for every camera ID."""

    def __init__(self, **tracker_options: float) -> None:
        self._tracker_options = tracker_options
        self._trackers: dict[str, CameraPersonTracker] = {}

    def for_camera(self, camera_id: str) -> CameraPersonTracker:
        if not camera_id.strip():
            raise ValueError("camera_id must not be empty")
        return self._trackers.setdefault(camera_id, CameraPersonTracker(**self._tracker_options))
