"""
二重線の壁（平行する2本の線分）の検出と、壁芯に基づく面積の算出。

Stage 3 の第一歩。壁の内法・外法の2本の線から壁芯を求め、
部屋の境界が壁の内面に一致する場合に壁芯面積を算出する。
壁芯面積が求まらない部屋は「不明」のままにし、推測で値を
出さない。
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from shapely.geometry import LineString, Point, Polygon

from core.analyzer.units import _AREA_TO_M2
from core.models.drawing import Drawing, LineElement, PolylineElement
from core.models.room import Room

logger = logging.getLogger(__name__)

# 壁厚として認める範囲（mm）。日本の一般的な内壁 100〜200mm、
# 外壁 150〜300mm 程度をカバーし、寸法線などの誤検出を避ける。
MIN_WALL_THICKNESS_MM = 50.0
MAX_WALL_THICKNESS_MM = 500.0
# 平行とみなす角度差（度）。
ANGLE_TOLERANCE_DEG = 2.0
# 壁の2本の線が重なっているとみなす最小の重なり率。
MIN_OVERLAP_RATIO = 0.5
# 部屋の境界辺と壁の面が一致するとみなす最小の重なり率。
EDGE_MATCH_OVERLAP_RATIO = 0.8
# 同一線上とみなす距離の許容値（mm）。
COLLINEAR_TOLERANCE_MM = 1.0


@dataclass
class WallPair:
    """平行する2本の線分で表された壁。"""

    line_a: List[List[float]]
    line_b: List[List[float]]
    thickness: float  # 2本の線の距離（図面単位）
    centerline: List[List[float]]  # 重なり区間における壁芯
    overlap_ratio: float
    source_ids: Tuple[str, str] = ("", "")


@dataclass
class _Segment:
    p1: Tuple[float, float]
    p2: Tuple[float, float]
    source_id: str = ""

    @property
    def length(self) -> float:
        return math.hypot(self.p2[0] - self.p1[0], self.p2[1] - self.p1[1])

    @property
    def direction(self) -> Tuple[float, float]:
        length = self.length
        if length == 0:
            return (0.0, 0.0)
        return ((self.p2[0] - self.p1[0]) / length, (self.p2[1] - self.p1[1]) / length)

    @property
    def angle_deg(self) -> float:
        return math.degrees(math.atan2(self.p2[1] - self.p1[1], self.p2[0] - self.p1[0]))


def area_factor_for_units(units: str) -> float:
    """図面単位を m² へ換算する係数を返す。未対応の単位は ValueError。"""
    factor = _AREA_TO_M2.get((units or "").strip().lower())
    if factor is None:
        raise ValueError(f"Unsupported drawing area unit {units!r}")
    return factor


def collect_wall_segments(drawing: Drawing) -> List[_Segment]:
    """壁の候補となる直線分を図面から集める。

    LINE 要素と、ポリラインの直線辺（bulge のある辺は除く）を対象とする。
    """
    segments: List[_Segment] = []
    for elem in drawing.elements:
        if isinstance(elem, LineElement):
            try:
                p1 = (float(elem.start[0]), float(elem.start[1]))
                p2 = (float(elem.end[0]), float(elem.end[1]))
            except (TypeError, ValueError, IndexError):
                continue
            if math.hypot(p2[0] - p1[0], p2[1] - p1[1]) > 0:
                segments.append(_Segment(p1, p2, elem.element_id))
        elif isinstance(elem, PolylineElement):
            try:
                points = [(float(p[0]), float(p[1])) for p in elem.points]
                bulges = [float(v) for v in elem.bulge_list]
            except (TypeError, ValueError, IndexError):
                continue
            count = len(points)
            edges = count if elem.is_closed else count - 1
            for i in range(edges):
                if i < len(bulges) and abs(bulges[i]) > 1e-12:
                    continue
                p1 = points[i]
                p2 = points[(i + 1) % count]
                if math.hypot(p2[0] - p1[0], p2[1] - p1[1]) > 0:
                    segments.append(_Segment(p1, p2, elem.element_id))
    return segments


def _overlap_interval(a: _Segment, b: _Segment) -> Tuple[float, float, float]:
    """線分 b を線分 a の軸へ投影したときの重なりを返す。

    戻り値: (重なり長, a 上の開始位置, a 上の終了位置)。
    位置は a の始点からの距離。
    """
    ux, uy = a.direction
    t_b0 = (b.p1[0] - a.p1[0]) * ux + (b.p1[1] - a.p1[1]) * uy
    t_b1 = (b.p2[0] - a.p1[0]) * ux + (b.p2[1] - a.p1[1]) * uy
    lo = max(0.0, min(t_b0, t_b1))
    hi = min(a.length, max(t_b0, t_b1))
    return max(0.0, hi - lo), lo, hi


def _centerline_over_overlap(a: _Segment, b: _Segment, lo: float, hi: float) -> List[List[float]]:
    """重なり区間における2本の線の中間線を返す。"""
    ux, uy = a.direction
    vx, vy = b.direction
    points = []
    for t in (lo, hi):
        ax = a.p1[0] + ux * t
        ay = a.p1[1] + uy * t
        # b 上で a の点 t に対応する点（b へ射影する）。
        s = (ax - b.p1[0]) * vx + (ay - b.p1[1]) * vy
        bx = b.p1[0] + vx * s
        by = b.p1[1] + vy * s
        points.append([(ax + bx) / 2.0, (ay + by) / 2.0])
    return points


def _candidate_pairs(segments: List[_Segment], max_distance: float) -> List[Tuple[int, int]]:
    """最大距離以内にあり得る線分の組を空間グリッドで絞り込む。

    各線分を、最大距離だけ広げた外接矩形が触れるセルへ登録し、
    同じセルに入った組だけを返す。線分同士の距離が最大距離を
    超える組は決して同じセルに入らない。
    """
    if not segments or max_distance <= 0:
        return []
    cell = max_distance
    grid: dict[Tuple[int, int], List[int]] = {}
    for index, seg in enumerate(segments):
        min_x = min(seg.p1[0], seg.p2[0]) - max_distance
        max_x = max(seg.p1[0], seg.p2[0]) + max_distance
        min_y = min(seg.p1[1], seg.p2[1]) - max_distance
        max_y = max(seg.p1[1], seg.p2[1]) + max_distance
        for cx in range(math.floor(min_x / cell), math.floor(max_x / cell) + 1):
            for cy in range(math.floor(min_y / cell), math.floor(max_y / cell) + 1):
                grid.setdefault((cx, cy), []).append(index)
    seen: set[Tuple[int, int]] = set()
    for indices in grid.values():
        for a_pos in range(len(indices)):
            for b_pos in range(a_pos + 1, len(indices)):
                i, j = indices[a_pos], indices[b_pos]
                if i > j:
                    i, j = j, i
                seen.add((i, j))
    return sorted(seen)


def detect_wall_pairs(
    drawing: Drawing,
    min_thickness_mm: float = MIN_WALL_THICKNESS_MM,
    max_thickness_mm: float = MAX_WALL_THICKNESS_MM,
) -> List[WallPair]:
    """平行する2本の線分の組（壁）を検出する。

    各線分は最も近い平行線とのみ組にする（1本の線が複数の壁に
    属することはない、という前提）。厚さは図面単位に換算して判定する。
    """
    area_factor = area_factor_for_units(drawing.units)
    mm_per_unit = 1000.0 * math.sqrt(area_factor)
    min_thickness = min_thickness_mm / mm_per_unit
    max_thickness = max_thickness_mm / mm_per_unit

    segments = collect_wall_segments(drawing)
    # 空間グリッドによる事前絞り込み。最大壁厚より離れた線分同士は
    # 壁にならないため、同じセル（または隣接セル）にある線分だけを
    # 比較する。グリッドなしの総当たりでは実図面で数秒かかる。
    candidates = _candidate_pairs(segments, max_thickness)
    # 各線分について最も近い平行線との候補を集める。
    best: dict[int, Tuple[float, int, WallPair]] = {}
    for i, j in candidates:
        a, b = segments[i], segments[j]
        line_a = LineString([a.p1, a.p2])
        angle_diff = abs(a.angle_deg - b.angle_deg) % 180.0
        if angle_diff > 90.0:
            angle_diff = 180.0 - angle_diff
        if angle_diff > ANGLE_TOLERANCE_DEG:
            continue
        line_b = LineString([b.p1, b.p2])
        distance = float(line_a.distance(line_b))
        if distance < min_thickness or distance > max_thickness:
            continue
        overlap, lo, hi = _overlap_interval(a, b)
        shorter = min(a.length, b.length)
        if shorter == 0 or overlap / shorter < MIN_OVERLAP_RATIO:
            continue
        pair = WallPair(
            line_a=[[a.p1[0], a.p1[1]], [a.p2[0], a.p2[1]]],
            line_b=[[b.p1[0], b.p1[1]], [b.p2[0], b.p2[1]]],
            thickness=distance,
            centerline=_centerline_over_overlap(a, b, lo, hi),
            overlap_ratio=overlap / shorter,
            source_ids=(a.source_id, b.source_id),
        )
        for index in (i, j):
            current = best.get(index)
            if current is None or distance < current[0]:
                best[index] = (distance, j if index == i else i, pair)

    # 同じ組の重複を除く（2本の線の座標で識別する。source_id は
    # ポリラインの辺で共有されるため識別子には使えない）。
    seen: set[tuple] = set()
    pairs: List[WallPair] = []
    for _, (_, other, pair) in sorted(best.items()):
        key = tuple(
            sorted(
                [
                    tuple(map(tuple, pair.line_a)),
                    tuple(map(tuple, pair.line_b)),
                ]
            )
        )
        if key in seen:
            continue
        seen.add(key)
        pairs.append(pair)
    logger.info("二重線の壁を検出: %d 組（線分 %d 本）", len(pairs), len(segments))
    return pairs


def _signed_area(points: List[Tuple[float, float]]) -> float:
    total = 0.0
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _simplify_collinear(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """一直線上の連続する点を除く（180°の角をなくす）。"""
    if len(points) <= 3:
        return list(points)
    simplified = [points[0]]
    for i in range(1, len(points)):
        p_prev = simplified[-1]
        p_curr = points[i]
        p_next = points[(i + 1) % len(points)]
        cross = (p_curr[0] - p_prev[0]) * (p_next[1] - p_curr[1]) - (
            p_curr[1] - p_prev[1]
        ) * (p_next[0] - p_curr[0])
        if abs(cross) > 1e-9:
            simplified.append(p_curr)
    # 始点自体が一直線上の点だった場合も除く。
    if len(simplified) > 3:
        p_prev, p_curr, p_next = simplified[-1], simplified[0], simplified[1]
        cross = (p_curr[0] - p_prev[0]) * (p_next[1] - p_curr[1]) - (
            p_curr[1] - p_prev[1]
        ) * (p_next[0] - p_curr[0])
        if abs(cross) <= 1e-9:
            simplified.pop(0)
    return simplified


def _match_edge_to_wall(
    edge: _Segment,
    wall_pairs: List[WallPair],
    collinear_tol: float,
) -> Optional[Tuple[WallPair, float, List[List[float]]]]:
    """境界辺に一致する壁の面を探す。戻り値は (壁, 厚さ, 反対側の面)。"""
    line_edge = LineString([edge.p1, edge.p2])
    best: Optional[Tuple[WallPair, float, List[List[float]]]] = None
    best_overlap = 0.0
    for pair in wall_pairs:
        for side, other in ((pair.line_a, pair.line_b), (pair.line_b, pair.line_a)):
            side_seg = _Segment((side[0][0], side[0][1]), (side[1][0], side[1][1]))
            angle_diff = abs(edge.angle_deg - side_seg.angle_deg) % 180.0
            if angle_diff > 90.0:
                angle_diff = 180.0 - angle_diff
            if angle_diff > ANGLE_TOLERANCE_DEG:
                continue
            line_side = LineString([side_seg.p1, side_seg.p2])
            if float(line_edge.distance(line_side)) > collinear_tol:
                continue
            overlap, _, _ = _overlap_interval(edge, side_seg)
            ratio = overlap / edge.length if edge.length > 0 else 0.0
            if ratio >= EDGE_MATCH_OVERLAP_RATIO and ratio > best_overlap:
                best = (pair, pair.thickness, other)
                best_overlap = ratio
    return best


def compute_centerline_area(
    boundary: List[List[float]],
    wall_pairs: List[WallPair],
    mm_per_unit: float,
) -> Optional[Tuple[float, List[float]]]:
    """境界の各辺を壁芯まで外側へずらした多角形の面積を返す。

    戻り値は (面積（図面単位の2乗）, 各辺の壁厚（mm）)。
    1辺でも対応する壁が見つからない場合や、ずらした多角形が
    不正な場合は None を返す（推測しない）。
    """
    if len(boundary) < 3:
        return None
    try:
        points = [(float(p[0]), float(p[1])) for p in boundary]
    except (TypeError, ValueError, IndexError):
        return None
    if not all(math.isfinite(x) and math.isfinite(y) for x, y in points):
        return None
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    points = _simplify_collinear(points)
    if len(points) < 3:
        return None

    collinear_tol = COLLINEAR_TOLERANCE_MM / mm_per_unit
    # 多角形の向き：正の符号付き面積なら反時計回り。外側は
    # 反時計回りでは辺の右側、時計回りでは辺の左側。
    ccw = _signed_area(points) > 0
    room_polygon = Polygon(points)
    thicknesses: List[float] = []
    offset_lines: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
    count = len(points)
    for i in range(count):
        p1 = points[i]
        p2 = points[(i + 1) % count]
        edge = _Segment(p1, p2)
        matched = _match_edge_to_wall(edge, wall_pairs, collinear_tol)
        if matched is None:
            return None
        _, thickness, other_side = matched
        # 壁の反対側の面が部屋の内側にある場合は、この境界は
        # 壁の外面のループ（部屋ではない）なので対象外とする。
        mid_other = (
            (other_side[0][0] + other_side[1][0]) / 2.0,
            (other_side[0][1] + other_side[1][1]) / 2.0,
        )
        if room_polygon.contains(Point(mid_other)):
            return None
        thicknesses.append(thickness * mm_per_unit)
        # 辺の外向き法線へ厚さの半分だけずらす。
        ux, uy = edge.direction
        nx, ny = (uy, -ux) if ccw else (-uy, ux)
        offset = thickness / 2.0
        q1 = (p1[0] + nx * offset, p1[1] + ny * offset)
        q2 = (p2[0] + nx * offset, p2[1] + ny * offset)
        offset_lines.append((q1, q2))

    # 隣り合うずらした辺の交点を新しい頂点とする。
    new_points: List[Tuple[float, float]] = []
    for i in range(count):
        (a1, a2) = offset_lines[i - 1]
        (b1, b2) = offset_lines[i]
        denom = (a2[0] - a1[0]) * (b2[1] - b1[1]) - (a2[1] - a1[1]) * (b2[0] - b1[0])
        if abs(denom) < 1e-12:
            return None
        t = ((b1[0] - a1[0]) * (b2[1] - b1[1]) - (b1[1] - a1[1]) * (b2[0] - b1[0])) / denom
        new_points.append((a1[0] + t * (a2[0] - a1[0]), a1[1] + t * (a2[1] - a1[1])))

    try:
        polygon = Polygon(new_points)
    except (TypeError, ValueError):
        return None
    if not polygon.is_valid or polygon.is_empty:
        return None
    area = float(polygon.area)
    inner_area = abs(_signed_area(points))
    if not math.isfinite(area) or area <= 0 or area < inner_area:
        return None
    return area, thicknesses


def attach_wall_info(
    rooms: List[Room],
    wall_pairs: List[WallPair],
    area_factor: float,
) -> int:
    """部屋一覧へ壁の情報を付与する。

    すべての境界辺が壁の面に一致する部屋は wall_type を "inner"
    （境界は内法）とし、壁芯面積を properties へ入れる。
    壁芯面積を算出できた部屋の件数を返す。
    """
    if not wall_pairs:
        return 0
    mm_per_unit = 1000.0 * math.sqrt(area_factor)
    attached = 0
    for room in rooms:
        result = compute_centerline_area(room.boundary, wall_pairs, mm_per_unit)
        if result is None:
            continue
        area_units2, thicknesses = result
        room.wall_type = "inner"
        room.properties["area_centerline_m2"] = float(area_units2) * area_factor
        room.properties["wall_thicknesses_mm"] = [round(t, 1) for t in thicknesses]
        attached += 1
    if attached:
        logger.info("壁芯面積を算出できた部屋: %d 件", attached)
    return attached
