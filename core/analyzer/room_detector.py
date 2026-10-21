"""Deterministic first-pass room candidate extraction from DXF geometry.

Recognizes explicit closed straight-sided polylines and polygons enclosed by
connected LINE entities, with conservative endpoint snapping for tiny gaps.
Candidates remain provisional: room labels, wall thickness, and wall centerlines
are not inferred.
"""
from __future__ import annotations

import math
import re
from dataclasses import replace
from typing import List

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union

from core.models.drawing import Drawing, LineElement, PolylineElement, TextElement
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
    polylines, self-intersecting boundaries, degenerate shapes, non-finite
    coordinates, and polylines containing bulge arcs are skipped to avoid
    reporting misleading areas.

    Returned Room objects have an empty name and confidence 0.5: they are
    geometric candidates, not confirmed rooms. Boundary coordinates remain
    in source drawing units; area_m2 is converted using drawing.units.

    Raises:
        ValueError: If min_area_m2 is not a finite non-negative number or the
            drawing uses a unit not supported by the conversion table.
    """
    try:
        threshold = float(min_area_m2)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("min_area_m2 must be a finite non-negative number") from exc
    if not math.isfinite(threshold) or threshold < 0:
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

        try:
            bulges = [float(value) for value in elem.bulge_list]
        except (TypeError, ValueError, OverflowError):
            continue
        if any(not math.isfinite(value) or abs(value) > 1e-12 for value in bulges):
            continue

        try:
            points = [(float(point[0]), float(point[1])) for point in elem.points]
        except (TypeError, ValueError, IndexError, OverflowError):
            continue
        if not all(math.isfinite(x) and math.isfinite(y) for x, y in points):
            continue

        # Remove a repeated final point; Polygon closes its ring itself.
        if len(points) > 1 and points[0] == points[-1]:
            points.pop()
        if len(set(points)) < 3:
            continue

        try:
            polygon = Polygon(points)
            if not polygon.is_valid or polygon.is_empty:
                continue
            area_m2 = float(polygon.area) * area_factor
        except (TypeError, ValueError, OverflowError):
            continue

        if not math.isfinite(area_m2) or area_m2 < threshold:
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



def detect_linework_room_candidates(
    drawing: Drawing,
    min_area_m2: float = 1.0,
    gap_tolerance: float | None = None,
) -> List[Room]:
    """Find provisional room polygons enclosed by connected LINE entities.

    This supplements closed-polyline detection for drawings whose boundaries
    are represented as separate line segments. By default, endpoint snapping
    uses a tolerance equivalent to 1 mm in the drawing's source units. Pass an
    explicit gap_tolerance to override it. Excessive tolerances can incorrectly
    connect nearby geometry. Results are provisional; text labels and wall
    thickness are not inferred.
    """
    try:
        threshold = float(min_area_m2)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("min_area_m2 must be a finite non-negative number") from exc
    if not math.isfinite(threshold) or threshold < 0:
        raise ValueError("min_area_m2 must be a finite non-negative number")

    unit = (drawing.units or "").strip().lower()
    area_factor = _AREA_TO_M2.get(unit)
    if area_factor is None:
        raise ValueError(
            f"Unsupported drawing area unit {drawing.units!r}; "
            f"supported units: {', '.join(sorted(_AREA_TO_M2))}"
        )

    if gap_tolerance is None:
        # Keep the default geometric tolerance consistent across unit systems.
        tolerance = 0.001 / math.sqrt(area_factor)
    else:
        try:
            tolerance = float(gap_tolerance)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("gap_tolerance must be a finite non-negative number") from exc
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("gap_tolerance must be a finite non-negative number")

    line_records = []
    for elem in drawing.elements:
        if not isinstance(elem, LineElement):
            continue
        try:
            start = (float(elem.start[0]), float(elem.start[1]))
            end = (float(elem.end[0]), float(elem.end[1]))
        except (TypeError, ValueError, IndexError, OverflowError):
            continue
        if not all(math.isfinite(v) for v in (*start, *end)) or start == end:
            continue
        line = LineString([start, end])
        if line.is_empty or line.length == 0:
            continue
        line_records.append((elem.element_id, line))

    if len(line_records) < 3:
        return []

    # Cluster nearby endpoints, then rebuild each segment using the shared
    # representative coordinate. This closes tiny endpoint gaps without
    # buffering or expanding whole wall lines.
    if tolerance > 0:
        endpoints = []
        for _, line in line_records:
            endpoints.extend([tuple(line.coords[0]), tuple(line.coords[-1])])
        parent = list(range(len(endpoints)))

        def find(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        cluster_members = {index: [index] for index in range(len(endpoints))}

        def union(left, right):
            root_left, root_right = find(left), find(right)
            if root_left == root_right:
                return
            # Prevent single-linkage chaining: every pair of endpoints in the
            # merged cluster must remain within the configured tolerance.
            left_members = cluster_members[root_left]
            right_members = cluster_members[root_right]
            if any(
                math.hypot(
                    endpoints[left_index][0] - endpoints[right_index][0],
                    endpoints[left_index][1] - endpoints[right_index][1],
                ) > tolerance
                for left_index in left_members
                for right_index in right_members
            ):
                return
            parent[root_right] = root_left
            left_members.extend(right_members)
            del cluster_members[root_right]

        cells = {}
        for index, (x, y) in enumerate(endpoints):
            cell = (math.floor(x / tolerance), math.floor(y / tolerance))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for other in cells.get((cell[0] + dx, cell[1] + dy), []):
                        ox, oy = endpoints[other]
                        if math.hypot(x - ox, y - oy) <= tolerance:
                            union(index, other)
            cells.setdefault(cell, []).append(index)

        clusters = {}
        for index, point in enumerate(endpoints):
            clusters.setdefault(find(index), []).append(point)
        representatives = {
            root: (sum(p[0] for p in points) / len(points),
                   sum(p[1] for p in points) / len(points))
            for root, points in clusters.items()
        }
        snapped_records = []
        for line_index, (element_id, line) in enumerate(line_records):
            start_index, end_index = line_index * 2, line_index * 2 + 1
            start = representatives[find(start_index)]
            end = representatives[find(end_index)]
            if start != end:
                snapped_records.append((element_id, LineString([start, end])))
        line_records = snapped_records

    try:
        noded_lines = unary_union([line for _, line in line_records])
        polygons = list(polygonize(noded_lines))
    except (TypeError, ValueError, OverflowError):
        return []

    # Room.boundary stores one exterior ring only. Nested loops (often caused
    # by wall thickness or shafts) can produce polygons with holes and a
    # second polygon inside the hole. Emitting either would make the stored
    # boundary disagree with area_m2 or create a misleading room candidate.
    # Conservatively skip both members of any nested pair.
    nested_indices = {
        index for index, polygon in enumerate(polygons) if polygon.interiors
    }
    exterior_shells = []
    for polygon in polygons:
        try:
            exterior_shells.append(Polygon(polygon.exterior))
        except (TypeError, ValueError):
            exterior_shells.append(None)
    for left_index, left in enumerate(polygons):
        if left.is_empty or left.area <= 0:
            continue
        try:
            left_point = left.representative_point()
        except (TypeError, ValueError):
            continue
        for right_index, right_shell in enumerate(exterior_shells):
            if left_index == right_index or right_shell is None:
                continue
            if right_shell.area <= left.area:
                continue
            try:
                if right_shell.contains(left_point):
                    nested_indices.add(left_index)
                    nested_indices.add(right_index)
            except (TypeError, ValueError):
                continue

    candidates: List[Room] = []
    for polygon_index, polygon in enumerate(polygons):
        try:
            if polygon_index in nested_indices or polygon.is_empty or not polygon.is_valid:
                continue
            area_m2 = float(polygon.area) * area_factor
            if not math.isfinite(area_m2) or area_m2 < threshold:
                continue
            boundary = [[float(x), float(y)] for x, y in list(polygon.exterior.coords)[:-1]]
            source_ids = [
                element_id
                for element_id, line in line_records
                if line.intersects(polygon.boundary)
            ]
        except (TypeError, ValueError, OverflowError):
            continue

        if len(boundary) < 3:
            continue
        candidates.append(
            Room(
                room_id=f"ROOM_LINEWORK_{len(candidates) + 1:06d}",
                room_name="",
                area_m2=area_m2,
                boundary=boundary,
                wall_type="unknown",
                confidence=0.4,
                properties={
                    "source_element_ids": source_ids,
                    "candidate_type": "closed_linework",
                    "area_source_unit": unit,
                },
            )
        )

    return candidates


def deduplicate_room_candidates(polyline_rooms: List[Room], linework_rooms: List[Room]) -> List[Room]:
    """Suppress coincident linework candidates when a closed polyline already exists.

    Geometric equality is evaluated using symmetric-difference area, not vertex
    order. Partial overlaps and adjacent rooms remain separate candidates.
    """
    accepted = list(polyline_rooms)
    polygons = []
    for room in polyline_rooms:
        try:
            polygon = Polygon(room.boundary)
            if polygon.is_valid and not polygon.is_empty and polygon.area > 0:
                polygons.append(polygon)
        except (TypeError, ValueError):
            continue

    for room in linework_rooms:
        try:
            polygon = Polygon(room.boundary)
            if polygon.is_valid and not polygon.is_empty and polygon.area > 0:
                duplicate = any(
                    polygon.symmetric_difference(existing).area
                    <= max(polygon.area, existing.area) * 1e-9
                    for existing in polygons
                )
                if duplicate:
                    continue
                polygons.append(polygon)
        except (TypeError, ValueError):
            pass
        accepted.append(room)
    return accepted



def associate_room_names(drawing: Drawing, rooms: List[Room]) -> List[Room]:
    """Conservatively associate a single text label with each room candidate.

    A label is accepted only when its insertion point lies strictly inside
    exactly one candidate polygon, its text is not numeric/dimension-like, and
    that room contains exactly one eligible label. Ambiguous cases remain
    unnamed. This is a first-pass geometric association, not semantic room-name
    recognition.
    """
    text_records = []
    for element in drawing.elements:
        if not isinstance(element, TextElement):
            continue
        label = re.sub(r"\\P", " ", str(element.text or "")).strip()
        label = re.sub(r"\s+", " ", label)
        if not label or re.fullmatch(
            r"[0-9０-９.,，．+＋−±×xX*/=()（）㎡mＭｍ²³\s-]+", label
        ):
            continue
        try:
            x, y = float(element.insertion_point[0]), float(element.insertion_point[1])
        except (TypeError, ValueError, IndexError, OverflowError):
            continue
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        text_records.append((element, label, Point(x, y)))

    room_polygons = []
    for room in rooms:
        try:
            polygon = Polygon(room.boundary)
            if polygon.is_valid and not polygon.is_empty and polygon.area > 0:
                room_polygons.append((room, polygon))
        except (TypeError, ValueError):
            continue

    # Use object identity rather than room_id: callers may supply externally
    # created candidates whose IDs are duplicated. Such candidates must not
    # accidentally share text associations.
    labels_by_room = {id(room): [] for room, _ in room_polygons}
    for element, label, point in text_records:
        matching = []
        for room, polygon in room_polygons:
            try:
                if polygon.contains(point):
                    matching.append(room)
            except (TypeError, ValueError):
                continue
        # Do not guess when candidates overlap or share an interior.
        if len(matching) == 1:
            labels_by_room[id(matching[0])].append((element, label))

    associated = []
    for room in rooms:
        matches = labels_by_room.get(id(room), [])
        if len(matches) == 1:
            element, label = matches[0]
            properties = {
                **room.properties,
                "room_name_source_element_id": element.element_id,
                "room_name_association": "single_text_inside_candidate",
            }
            associated.append(replace(room, room_name=label, properties=properties))
        else:
            associated.append(room)
    return associated
