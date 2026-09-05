"""Detector adapter producing tracker-ready people for Student Affairs."""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from staff_uniform_detector import YellowUniformDetector
from .zones import bbox_footpoint


@dataclass(frozen=True)
class PersonCandidate:
    bbox: tuple[int, int, int, int]
    confidence: float
    yellow_score: float
    blue_score: float
    footpoint: tuple[float, float]


class StudentAffairsDetector:
    """Adapter that has no count-based API by design."""

    def __init__(self, detector: YellowUniformDetector | None = None) -> None:
        self._detector = detector or YellowUniformDetector()

    def detect(self, image: Image.Image) -> list[PersonCandidate]:
        candidates: list[PersonCandidate] = []
        for item in self._detector.detect_people(image):
            bbox = tuple(item["bbox"])
            candidates.append(
                PersonCandidate(
                    bbox=bbox,
                    confidence=float(item["confidence"]),
                    yellow_score=float(item["yellow_score"]),
                    blue_score=float(item["blue_score"]),
                    footpoint=bbox_footpoint(bbox, *image.size),
                )
            )
        return candidates
