"""Deterministic first-pass room candidate extraction from DXF geometry.

This module deliberately does not infer walls from arbitrary line networks or
associate room labels. It only recognizes explicit, closed, straight-sided
polylines that form valid polygons, providing a conservative foundation for
later room-boundary detection.
"""
from __future__ import annotations

import math
from typing import List

from shapely.geometry import Polygon

from core.models.drawing import Drawing, PolylineElement
from core.models.room import Room


_AREA_TO_M2 = {
    "mm": 1e-6,
    "millimeter": 1e-6,
    "millimeters": 1e-6,
    "cm": 1e-4,
    "centimeter": 1e-4,
    "centimeters": 1e-4,
    "m": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "in": 0.0254**2,
    "inch": 0.0254**2,
    "inches": 0.0254**2,
    "ft": 0.3048**2,
    "foot": 0.3048**2,
    "feet": 0.3048**2,
}


def detect_closed_polyline_room_candidates(
    drawing: Drawing,
    min_area_m2: float = 1.0,
) -> List[Room]:
    """Return provisional room candidates from explicit closed polylines.

    Only closed, valid polygons with straight segments are considered. Open
    polylines, self-intersecting boundaries, degenerate shapes, and polylines
    containing bulge arcs are skipped to avoid reporting misleading areas.

    The returned `Room` objects have an empty name and a confidence of 0.5:
    they are geometric candidates, not confirmed rooms. Coordinates in
    `boundary` remain in the source drawing's units; `area_m2` is converted
    to square metres based on `drawing.units`.

    Args:
        drawing: Parsed drawing whose elements use a consistent coordinate unit.
        min_area_m2: Minimum polygon area in square metres (inclusive).

    Raises:
        ValueError: If the minimum area is negative/non-finite or the drawing
            uses a unit not supported by the conversion table.
    """
    if not math.isfinite(min_area_m2) or min_area_m2 < 0:
        raise ValueError("min_area_m2 must be a finite non-negative number")

    unit = (drawing.units or "").strip().lower()
    area_factor = _AREA_TO_M2.get(unit)
    if area_factor is None:
        raise ValueError(
            f"Unsupported drawing area unit {drawing.units!r}; "
            f"supported units: {', '.join(sorted(_AREA_TO_M2))}"
        )

    candidates: List[Room] = []
    for elem in drawing.elements:
        if not isinstance(elem, PolylineElement) or not elem.is_closed:
            continue
        if len(elem.points) < 3:
            continue
        if any(abs(value) > 1e-12 for value in elem.bulge_list):
            continue

        points = [(float(point[0]), float(point[1])) for point in elem.points]
        # Remove a repeated final point; Polygon closes its ring itself.
        if len(points) > 1 and points[0] == points[-1]:
            points.pop()
        if len(set(points)) < 3:
            continue

        polygon = Polygon(points)
        if not polygon.is_valid or polygon.is_empty:
            continue

        area_m2 = float(polygon.area) * area_factor
        if not math.isfinite(area_m2) or area_m2 < min_area_m2:
            continue

        candidates.append(
            Room(
                room_id=f"ROOM_CANDIDATE_{len(candidates) + 1:06d}",
                room_name="",
                area_m2=area_m2,
                boundary=[[x, y] for x, y in points],
                wall_type="unknown",
                confidence=0.5,
                properties={
                    "source_element_id": elem.element_id,
                    "source_layer": elem.layer,
                    "candidate_type": "closed_straight_polyline",
                    "area_source_unit": unit,
                },
            )
        )

    return candidates
