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
from core.analyzer.units import _AREA_TO_M2
from core.analyzer.wall_detector import collect_wall_segments, detect_wall_pairs


# 部屋名の関連付けで許容する、境界からのずれ (mm)。挿入点が部屋のすぐ外に
# ある文字を拾うためのもので、壁厚 (100-200mm) を大きく超えない値にする。
_NAME_NEAR_TOLERANCE_MM = 100.0


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
    """Suppress geometrically identical room candidates.

    Closed-polyline candidates take priority over linework candidates, and
    identical geometry is kept only once no matter which detector produced
    it (for example the same boundary drawn on two layers). Geometric
    equality is evaluated using symmetric-difference area, not vertex
    order. Partial overlaps and adjacent rooms remain separate candidates.
    Candidates whose boundary cannot form a valid polygon are dropped
    instead of being passed through unchecked.
    """
    accepted: List[Room] = []
    polygons = []
    for room in list(polyline_rooms) + list(linework_rooms):
        try:
            polygon = Polygon(room.boundary)
        except (TypeError, ValueError):
            continue
        if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
            continue
        duplicate = any(
            polygon.symmetric_difference(existing).area
            <= max(polygon.area, existing.area) * 1e-9
            for existing in polygons
        )
        if duplicate:
            continue
        polygons.append(polygon)
        accepted.append(room)
    return accepted



def detect_wall_pair_room_candidates(
    drawing: Drawing,
    wall_pairs=None,
    min_area_m2: float = 1.0,
) -> List[Room]:
    """壁ペアに参加する線分だけから部屋候補を検出する。

    実図面では同じ壁が仕上・断熱・躯体など複数の画層に分かれて描かれ、
    全線分で検出すると壁の内法面で小さな部屋になったり、共用部のような
    大きな部屋が断片化したりする。壁ペア (平行する2本の線分) に参加する
    線分だけに絞ると、壁面に沿った本来の部屋境界が得られやすい。
    壁ペアに参加しない単線の壁は拾えないため、この関数の結果は
    全線分の検出結果と組み合わせて使う (merge_room_candidates)。
    返される部屋の room_id は ROOM_WALLPAIR_ から始まり、candidate_type は
    "wall_pair_linework" になる。
    """
    if wall_pairs is None:
        wall_pairs = detect_wall_pairs(drawing)
    if not wall_pairs:
        return []
    pair_source_ids = set()
    for pair in wall_pairs:
        pair_source_ids.update(pair.source_ids)
    wall_lines = []
    for segment in collect_wall_segments(drawing):
        if segment.source_id not in pair_source_ids:
            continue
        wall_lines.append(
            LineElement(
                element_id=f"WALLPAIR_{len(wall_lines):05d}",
                element_type="LINE",
                layer="0",
                start=[float(segment.p1[0]), float(segment.p1[1])],
                end=[float(segment.p2[0]), float(segment.p2[1])],
            )
        )
    if not wall_lines:
        return []
    sub_drawing = replace(drawing, elements=wall_lines)
    rooms = detect_linework_room_candidates(sub_drawing, min_area_m2=min_area_m2)
    renamed = []
    for index, room in enumerate(rooms):
        properties = {**room.properties, "candidate_type": "wall_pair_linework"}
        renamed.append(
            replace(
                room,
                room_id=f"ROOM_WALLPAIR_{index + 1:06d}",
                properties=properties,
            )
        )
    return renamed


def _polygon_iou(left: Polygon, right: Polygon) -> float:
    """2 つの多角形の IoU (積集合 / 和集合) を返す。"""
    try:
        union_area = left.union(right).area
    except (TypeError, ValueError):
        return 0.0
    if union_area <= 0:
        return 0.0
    try:
        return left.intersection(right).area / union_area
    except (TypeError, ValueError):
        return 0.0


def merge_room_candidates(
    all_lines_rooms: List[Room],
    wall_pair_rooms: List[Room],
    iou_threshold: float = 0.5,
) -> List[Room]:
    """全線分の部屋候補と壁ペア線分の部屋候補を統合する。

    同じ物理的な部屋が両方の検出で見つかる場合、壁ペア版を優先する
    (境界が壁面に沿うため面積が本来の部屋広さに近い)。重なりが
    iou_threshold 未満の候補は別々の部屋として両方残す。
    無効な境界の候補は落とす。呼び出し前に deduplicate_room_candidates で
    完全に同一の形状は除去しておくこと。
    """
    merged: List[Room] = []
    merged_polygons: List[Polygon] = []
    for room in all_lines_rooms:
        try:
            polygon = Polygon(room.boundary)
        except (TypeError, ValueError):
            continue
        if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
            continue
        merged.append(room)
        merged_polygons.append(polygon)
    for room in wall_pair_rooms:
        try:
            polygon = Polygon(room.boundary)
        except (TypeError, ValueError):
            continue
        if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
            continue
        overlapped = [
            index
            for index, existing in enumerate(merged_polygons)
            if _polygon_iou(polygon, existing) >= iou_threshold
        ]
        if overlapped:
            for index in sorted(overlapped, reverse=True):
                del merged[index]
                del merged_polygons[index]
        merged.append(room)
        merged_polygons.append(polygon)
    return merged


def associate_room_names(drawing: Drawing, rooms: List[Room]) -> List[Room]:
    """Conservatively associate a single text label with each room candidate.

    A label is accepted only when its insertion point lies strictly inside
    exactly one candidate polygon, its text is not numeric/dimension-like, and
    that room contains exactly one eligible label. A label whose insertion
    point lies just outside a room (within 100 mm of the boundary) is
    accepted as a near match when exactly one room is near and that room
    has no exact label; the association is recorded as "text_near_candidate".
    Ambiguous cases remain unnamed. This is a first-pass geometric
    association, not semantic room-name recognition.
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
    unassigned = []
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
        elif len(matching) == 0:
            unassigned.append((element, label, point))

    # Second pass: a label whose insertion point lies just outside a room
    # (e.g. the text overflows the wall by a few cm on a real drawing) is
    # accepted when exactly one room boundary is within the tolerance and
    # that room has no exact label. The association is recorded separately
    # so the user can tell it apart from an exact match.
    near_labels_by_room = {id(room): [] for room, _ in room_polygons}
    tolerance = None
    try:
        area_factor = _AREA_TO_M2[(drawing.units or "").strip().lower()]
        tolerance = _NAME_NEAR_TOLERANCE_MM / (1000.0 * math.sqrt(area_factor))
    except KeyError:
        tolerance = None
    if tolerance is not None:
        for element, label, point in unassigned:
            near = []
            for room, polygon in room_polygons:
                try:
                    distance = polygon.distance(point)
                except (TypeError, ValueError):
                    continue
                # 境界線上の文字は対象外にする (contains と同じ扱い)。
                # 境界のすぐ外側にある文字だけを近接一致とする。
                if 0.0 < distance <= tolerance:
                    near.append(room)
            if len(near) == 1:
                near_labels_by_room[id(near[0])].append((element, label))

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
            continue
        near_matches = near_labels_by_room.get(id(room), [])
        if len(matches) == 0 and len(near_matches) == 1:
            element, label = near_matches[0]
            properties = {
                **room.properties,
                "room_name_source_element_id": element.element_id,
                "room_name_association": "text_near_candidate",
            }
            associated.append(replace(room, room_name=label, properties=properties))
            continue
        associated.append(room)
    return associated
