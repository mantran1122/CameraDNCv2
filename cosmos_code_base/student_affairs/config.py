"""Camera-profile loading and strict validation for the pilot."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

Point = tuple[float, float]


@dataclass(frozen=True)
class DeskConfig:
    id: str
    polygon: tuple[Point, ...]
    expected_staff: int


@dataclass(frozen=True)
class Thresholds:
    frame_interval_seconds: float
    absent_after_seconds: float
    exit_confirm_seconds: float
    crowd_warn_people: int
    crowd_confirm_seconds: float
    scene_change_threshold: float


@dataclass(frozen=True)
class CameraProfile:
    camera_id: str
    profile: str
    source_channel: int
    entrance: tuple[Point, ...]
    waiting: tuple[Point, ...]
    desks: tuple[DeskConfig, ...]
    thresholds: Thresholds


def _polygon(value: Any, field: str) -> tuple[Point, ...]:
    if not isinstance(value, list) or len(value) < 3:
        raise ValueError(f"{field} must contain at least three points")
    points: list[Point] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError(f"{field} points must be [x, y]")
        x, y = float(item[0]), float(item[1])
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise ValueError(f"{field} coordinates must be normalized to 0.0–1.0")
        points.append((x, y))
    return tuple(points)


def load_camera_profile(path: str | Path) -> CameraProfile:
    """Load a YAML profile and reject incomplete or unsafe zone definitions."""
    source = Path(path)
    try:
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read camera profile {source}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("camera profile must be a YAML mapping")
    zones = data.get("zones")
    thresholds = data.get("thresholds")
    if not isinstance(zones, dict) or not isinstance(thresholds, dict):
        raise ValueError("camera profile needs zones and thresholds mappings")
    desks_raw = zones.get("desks")
    if not isinstance(desks_raw, list) or not desks_raw:
        raise ValueError("zones.desks must contain at least one desk")
    desks: list[DeskConfig] = []
    seen_ids: set[str] = set()
    for raw in desks_raw:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            raise ValueError("each desk needs a string id")
        desk_id = raw["id"]
        if desk_id in seen_ids:
            raise ValueError(f"duplicate desk id: {desk_id}")
        expected = int(raw.get("expected_staff", 0))
        if expected < 1:
            raise ValueError(f"desk {desk_id} expected_staff must be at least 1")
        seen_ids.add(desk_id)
        desks.append(DeskConfig(desk_id, _polygon(raw.get("polygon"), f"desk {desk_id}"), expected))
    required = ("frame_interval_seconds", "absent_after_seconds", "exit_confirm_seconds", "crowd_warn_people", "crowd_confirm_seconds", "scene_change_threshold")
    if any(key not in thresholds for key in required):
        raise ValueError("thresholds is missing one or more required values")
    parsed_thresholds = Thresholds(**{key: thresholds[key] for key in required})
    if (parsed_thresholds.frame_interval_seconds <= 0 or parsed_thresholds.absent_after_seconds <= 0
            or parsed_thresholds.exit_confirm_seconds <= 0 or parsed_thresholds.crowd_warn_people < 1
            or parsed_thresholds.crowd_confirm_seconds <= 0 or not 0 < parsed_thresholds.scene_change_threshold <= 1):
        raise ValueError("threshold values are outside their valid ranges")
    return CameraProfile(
        camera_id=str(data.get("camera_id", "")).strip(), profile=str(data.get("profile", "")).strip(),
        source_channel=int(data.get("source_channel", 0)), entrance=_polygon(zones.get("entrance"), "zones.entrance"),
        waiting=_polygon(zones.get("waiting"), "zones.waiting"), desks=tuple(desks), thresholds=parsed_thresholds,
    )
