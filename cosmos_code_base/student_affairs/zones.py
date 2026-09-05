"""Geometry helpers operating on normalized image coordinates."""
from __future__ import annotations

from collections.abc import Sequence

Point = tuple[float, float]
Polygon = Sequence[Point]


def point_in_polygon(point: Point, polygon: Polygon) -> bool:
    """Return whether *point* is inside a polygon, including its boundary."""
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            cross_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x <= cross_x:
                inside = not inside
        previous = current
    return inside


def bbox_footpoint(box: Sequence[float], width: int, height: int) -> Point:
    """Return bottom-centre of a pixel bbox in normalized coordinates."""
    if width <= 0 or height <= 0:
        raise ValueError("image width and height must be positive")
    x1, _y1, x2, y2 = box
    return ((x1 + x2) / (2 * width), y2 / height)
