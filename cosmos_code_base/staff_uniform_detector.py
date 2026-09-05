"""Person-first yellow/blue uniform detection.

``detect`` remains a compatibility adapter for the existing admissions service.
Stateful camera pipelines must use ``detect_people`` and track each candidate,
never use a single-frame count as their source of truth.
"""
from __future__ import annotations

import os
from typing import Any

import cv2
import numpy as np
from PIL import Image


class YellowUniformDetector:
    """Detect people with YOLO, then classify only their upper-body colour."""

    def __init__(self) -> None:
        self._model = None

    def _get_model(self):
        if self._model is None:
            from ultralytics import YOLO

            self._model = YOLO(os.getenv("STAFF_DETECTOR_MODEL", "yolo11n.pt"))
        return self._model

    @staticmethod
    def _uniform_scores(person_bgr: np.ndarray) -> tuple[float, float]:
        height = person_bgr.shape[0]
        width = person_bgr.shape[1]
        # Keep the central upper body. Excluding box edges and the lower body
        # reduces yellow tables/chairs leaking into a seated person's score.
        top = int(height * 0.14)
        bottom = max(top + 1, int(height * 0.68))
        left = int(width * 0.14)
        right = max(left + 1, int(width * 0.86))
        torso = person_bgr[top:bottom, left:right]
        if torso.size == 0:
            return 0.0, 0.0
        hsv = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
        yellow = cv2.inRange(hsv, (18, 80, 100), (42, 255, 255))
        blue = cv2.inRange(hsv, (90, 45, 35), (135, 255, 255))
        total = float(torso.shape[0] * torso.shape[1])
        return float(np.count_nonzero(yellow) / total), float(np.count_nonzero(blue) / total)

    def detect_people(self, image: Image.Image) -> list[dict[str, Any]]:
        """Return one colour-scored candidate per detected person.

        Bounding boxes use pixel coordinates in ``[x1, y1, x2, y2]`` order.
        ``is_yellow_uniform_candidate`` is deliberately only a frame-level hint:
        the pilot tracker aggregates the scores over time before assigning staff
        presence to a desk.
        """
        rgb = np.asarray(image)
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        result = self._get_model().predict(
            source=bgr,
            classes=[0],  # COCO class 0: person
            conf=float(os.getenv("STAFF_PERSON_CONFIDENCE", "0.18")),
            imgsz=int(os.getenv("STAFF_DETECTOR_IMAGE_SIZE", "1280")),
            device=os.getenv("STAFF_DETECTOR_DEVICE", "cpu"),
            verbose=False,
        )[0]

        yellow_min = float(os.getenv("STAFF_YELLOW_RATIO", "0.055"))
        blue_min = float(os.getenv("STAFF_BLUE_RATIO", "0.003"))
        yellow_only_min = float(os.getenv("STAFF_YELLOW_ONLY_RATIO", "0.16"))
        boxes = result.boxes.xyxy.cpu().numpy()
        confidences = result.boxes.conf.cpu().numpy()
        candidates: list[dict[str, Any]] = []
        for box, confidence in zip(boxes, confidences):
            x1, y1, x2, y2 = box.astype(int)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(bgr.shape[1], x2), min(bgr.shape[0], y2)
            if x2 - x1 < 10 or y2 - y1 < 20:
                continue
            yellow_ratio, blue_ratio = self._uniform_scores(bgr[y1:y2, x1:x2])
            is_yellow = yellow_ratio >= yellow_min and (
                blue_ratio >= blue_min or yellow_ratio >= yellow_only_min
            )
            candidates.append(
                {
                    "bbox": [int(x1), int(y1), int(x2), int(y2)],
                    "confidence": float(confidence),
                    "yellow_score": yellow_ratio,
                    "blue_score": blue_ratio,
                    "is_yellow_uniform_candidate": is_yellow,
                }
            )
        return candidates

    def detect(self, image: Image.Image) -> dict[str, Any]:
        """Return legacy single-frame aggregate for the admissions endpoint."""
        candidates = self.detect_people(image)
        yellow_staff = sum(
            bool(candidate["is_yellow_uniform_candidate"])
            for candidate in candidates
        )

        return {
            "people_detected": len(candidates),
            "yellow_uniform_staff": yellow_staff,
            "method": "yolo_person_upper_body_colour",
            "people": candidates,
        }
