"""PDF（および Drawing 一般）の寸法の抽出・照合と倍率調整。

寸法テキスト（数値のみ）とその近くの寸法線をヒューリスティックで
見つけ、寸法線と平行な測定対象の線の実測長と寸法値を比較する。
曖昧な寸法は ``to_confirm``（要確認）とし、確定値として扱わない。

照合の許容誤差は、寸法値の 0.5% と 1mm のうち大きい方。
倍率調整は、寸法値 / 実測長（pt 単位）から正しい mm/pt 換算率を
求め、全要素の座標を拡大・縮小し直す。
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

from core.models.drawing import (
    Drawing, DrawingElement, LineElement, PolylineElement, TextElement,
    CircleElement, ArcElement, InsertElement,
)

logger = logging.getLogger(__name__)

# 照合の許容誤差（相対）。これ以下なら寸法通りとみなす。
_REL_TOLERANCE = 0.005
# 照合の許容誤差（絶対・mm）。相対誤差と比べて大きい方を使う。
_ABS_TOLERANCE_MM = 1.0

# 寸法線として確信できる確信度の下限。これ未満は要確認とする。
_CONFIDENT_THRESHOLD = 0.75
# 寸法線の候補として扱う確信度の下限。これ未満は寸法ではないとみなす。
_CANDIDATE_THRESHOLD = 0.5

# 寸法線の候補とする直線の最小長（図面単位。PDF では pt、DXF では mm）。
# 倍率が未確定の PDF では mm 換算ができないため、単位は図面座標のまま
# 小さな値にする。寸法線らしさは引出線とテキストの近さで判断する。
_MIN_DIMENSION_LINE_LENGTH = 2.0

# 寸法値として扱う最小値（mm）。部屋番号などの小さな数値（"2"、"3"）を
# 寸法と誤認しないための下限。
_MIN_DIMENSION_VALUE_MM = 50.0

# 寸法線の方向の許容誤差（度）。水平・垂直からこの範囲内なら軸平行とみなす。
_AXIS_ANGLE_TOL_DEG = 2.0
# 平行・直交の判定の許容誤差（度）。
_PARALLEL_ANGLE_TOL_DEG = 2.0
_PERPENDICULAR_ANGLE_TOL_DEG = 5.0

_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９．，", "0123456789.,")
_DIMENSION_VALUE_RE = re.compile(r"^\d+(\.\d+)?$")


# 照合状態の日本語表示。
STATUS_LABELS = {
    "matched": "一致",
    "mismatched": "不一致",
    "to_confirm": "要確認",
    "not_determinable": "判定不能",
}


@dataclass
class _Segment:
    """Drawing 内の直線区間（線要素・ポリラインの辺を共通化したもの）。"""
    p1: Tuple[float, float]
    p2: Tuple[float, float]
    element_id: str

    @property
    def length(self) -> float:
        return math.hypot(self.p2[0] - self.p1[0], self.p2[1] - self.p1[1])

    @property
    def angle_deg(self) -> float:
        """方向角（度、0〜180。向きは区別しない）。"""
        dx = self.p2[0] - self.p1[0]
        dy = self.p2[1] - self.p1[1]
        return math.degrees(math.atan2(dy, dx)) % 180.0

    @property
    def midpoint(self) -> Tuple[float, float]:
        return ((self.p1[0] + self.p2[0]) / 2.0, (self.p1[1] + self.p2[1]) / 2.0)


@dataclass
class DimensionCheck:
    """1 つの寸法についての照合結果。"""
    dimension_id: str
    value_mm: float
    dimension_text: str
    status: str  # "matched" | "mismatched" | "to_confirm" | "not_determinable"
    confidence: float
    measured_mm: Optional[float] = None
    measured_length_pt: Optional[float] = None
    difference_mm: Optional[float] = None
    tolerance_mm: Optional[float] = None
    dimension_line_id: Optional[str] = None
    measured_line_id: Optional[str] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def parse_dimension_value(text: str) -> Optional[float]:
    """寸法テキストから数値（mm）を取り出す。数値のみの場合は値を返す。

    カンマ区切り（"3,600"）・小数（"1200.5"）・全角数字・末尾の "mm" を
    許容する。数値以外を含むテキスト（部屋名・部屋番号の混じったもの等）
    は寸法とみなさず None を返す。0 以下の値も寸法ではない。
    """
    if text is None:
        return None
    cleaned = str(text).strip().translate(_FULLWIDTH_DIGITS)
    cleaned = cleaned.replace(",", "").replace(" ", "")
    if cleaned.lower().endswith("mm"):
        cleaned = cleaned[:-2]
    if not _DIMENSION_VALUE_RE.match(cleaned):
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def _collect_segments(drawing: Drawing) -> List[_Segment]:
    """Drawing 内のすべての直線区間を集める。"""
    segments: List[_Segment] = []
    for element in drawing.elements:
        if isinstance(element, LineElement):
            segments.append(_Segment(
                p1=(float(element.start[0]), float(element.start[1])),
                p2=(float(element.end[0]), float(element.end[1])),
                element_id=element.element_id,
            ))
        elif isinstance(element, PolylineElement):
            points = element.points
            if len(points) < 2:
                continue
            edge_count = len(points) if element.is_closed else len(points) - 1
            for i in range(edge_count):
                p1 = points[i]
                p2 = points[(i + 1) % len(points)]
                segments.append(_Segment(
                    p1=(float(p1[0]), float(p1[1])),
                    p2=(float(p2[0]), float(p2[1])),
                    element_id=element.element_id,
                ))
    return [s for s in segments if s.length > 0.0]


def _angle_diff_deg(a: float, b: float) -> float:
    """2 つの方向角（0〜180）の差（0〜90）。"""
    diff = abs(a - b) % 180.0
    return min(diff, 180.0 - diff)


def _is_axis_aligned(segment: _Segment) -> bool:
    angle = segment.angle_deg
    return (
        min(angle, 180.0 - angle) <= _AXIS_ANGLE_TOL_DEG
        or abs(angle - 90.0) <= _AXIS_ANGLE_TOL_DEG
    )


def _point_to_segment_distance(point: Tuple[float, float], segment: _Segment) -> Tuple[float, float]:
    """点から線分までの距離と、線分上の射影位置（0〜1、範囲外も可）を返す。"""
    px, py = point
    x1, y1 = segment.p1
    x2, y2 = segment.p2
    dx, dy = x2 - x1, y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq == 0.0:
        return math.hypot(px - x1, py - y1), 0.0
    t = ((px - x1) * dx + (py - y1) * dy) / length_sq
    t_clamped = max(0.0, min(1.0, t))
    closest = (x1 + t_clamped * dx, y1 + t_clamped * dy)
    return math.hypot(px - closest[0], py - closest[1]), t


def _text_center(element: TextElement) -> Tuple[float, float]:
    if element.bbox:
        return (
            (float(element.bbox[0]) + float(element.bbox[2])) / 2.0,
            (float(element.bbox[1]) + float(element.bbox[3])) / 2.0,
        )
    return (float(element.insertion_point[0]), float(element.insertion_point[1]))


def _find_dimension_line(
    text_element: TextElement,
    segments: List[_Segment],
) -> Tuple[Optional[_Segment], float, List[_Segment]]:
    """寸法テキストの近くにある寸法線の候補を探す。

    寸法線は、寸法テキストの近くにあり、両端に短い直交線（引出線）を
    持つ細い軸平行線とみなす。最も確信度の高い候補とその確信度、
    および見つかった引出線を返す。候補がなければ (None, 0.0, [])。
    """
    center = _text_center(text_element)
    font_height = max(float(text_element.height or 0.0), 1.0)
    best: Optional[_Segment] = None
    best_score = 0.0
    best_extensions: List[_Segment] = []

    for segment in segments:
        if not _is_axis_aligned(segment):
            continue
        if segment.length < _MIN_DIMENSION_LINE_LENGTH:
            continue
        distance, t = _point_to_segment_distance(center, segment)
        if distance > max(3.0 * font_height, 0.1 * segment.length):
            continue
        if t < -0.2 or t > 1.2:
            continue
        # 引出線：両端の近くにあり、寸法線と直交する短い線。
        extensions: List[_Segment] = []
        for endpoint in (segment.p1, segment.p2):
            for other in segments:
                if other is segment:
                    continue
                if _angle_diff_deg(other.angle_deg, segment.angle_deg) < 90.0 - _PERPENDICULAR_ANGLE_TOL_DEG:
                    continue
                if not (font_height <= other.length <= 1.0 * segment.length):
                    continue
                end_distance, _ = _point_to_segment_distance(endpoint, other)
                if end_distance <= max(2.0 * font_height, 0.02 * segment.length):
                    extensions.append(other)
                    break
        ends_with_extension = 0
        for endpoint in (segment.p1, segment.p2):
            if any(
                _point_to_segment_distance(endpoint, ext)[0]
                <= max(2.0 * font_height, 0.02 * segment.length)
                for ext in extensions
            ):
                ends_with_extension += 1
        score = 0.4
        if ends_with_extension == 2:
            score += 0.3
        elif ends_with_extension == 1:
            score += 0.15
        if distance <= 2.0 * font_height:
            score += 0.15
        if score > best_score:
            best = segment
            best_score = score
            best_extensions = extensions

    return best, best_score, best_extensions


def _find_measured_line_between_objects(
    dimension_line: _Segment,
    extensions: List[_Segment],
    segments: List[_Segment],
    font_height: float,
) -> Optional[_Segment]:
    """寸法が2つの対象線の間の距離を測っている場合の測定対象を探す。

    実図面の寸法は、平行な壁そのものの長さではなく、2本の水平線
    （壁）の間の垂直距離を測っていることが多い。その場合、測定対象の
    線は寸法線と平行には存在せず、引出線が指す2つの対象線の間の距離
    が実測長になる。各引出線について、その直線上にあり、寸法線から
    遠い側にある実際の対象線分（引出線・寸法線そのものは除く）を探し、
    両方の引出線で見つかれば、2つの対象線の間の距離を実測長とする。
    見つからなければ None。
    """
    if len(extensions) < 2:
        return None
    tolerance = max(2.0 * font_height, 0.02 * dimension_line.length)
    # 寸法線の軸方向と垂線方向。
    dx = dimension_line.p2[0] - dimension_line.p1[0]
    dy = dimension_line.p2[1] - dimension_line.p1[1]
    dim_length = math.hypot(dx, dy)
    if dim_length == 0.0:
        return None
    ux, uy = dx / dim_length, dy / dim_length

    def axis_param(point: Tuple[float, float]) -> float:
        return (point[0] - dimension_line.p1[0]) * ux + (point[1] - dimension_line.p1[1]) * uy

    def extension_axis_param(point: Tuple[float, float], ext: _Segment) -> float:
        ex = ext.p2[0] - ext.p1[0]
        ey = ext.p2[1] - ext.p1[1]
        elen = math.hypot(ex, ey)
        if elen == 0.0:
            return 0.0
        return ((point[0] - ext.p1[0]) * ex + (point[1] - ext.p1[1]) * ey) / elen

    object_ids: List[str] = []
    for endpoint in (dimension_line.p1, dimension_line.p2):
        # この端点に対応する引出線を探す。
        ext = None
        for candidate in extensions:
            end_distance, _ = _point_to_segment_distance(endpoint, candidate)
            if end_distance <= max(2.0 * font_height, 0.02 * dimension_line.length):
                ext = candidate
                break
        if ext is None:
            return None
        # 引出線の対象側の端（寸法線の端点から最も遠い端）。
        far_end = max(
            (ext.p1, ext.p2),
            key=lambda p: math.hypot(p[0] - endpoint[0], p[1] - endpoint[1]),
        )
        far_param = extension_axis_param(far_end, ext)
        # 引出線と同一線上にあり、対象側にある最も近い対象線分を探す。
        best: Optional[_Segment] = None
        best_distance = float("inf")
        for segment in segments:
            if segment is ext or segment is dimension_line:
                continue
            if _angle_diff_deg(segment.angle_deg, ext.angle_deg) > _PARALLEL_ANGLE_TOL_DEG:
                continue
            # 引出線の直線からの垂線距離。
            ex = ext.p2[0] - ext.p1[0]
            ey = ext.p2[1] - ext.p1[1]
            elen = math.hypot(ex, ey)
            if elen == 0.0:
                continue
            perp = abs(
                (segment.p1[0] - ext.p1[0]) * (-ey / elen)
                + (segment.p1[1] - ext.p1[1]) * (ex / elen)
            )
            if perp > tolerance:
                continue
            # 対象側（引出線の端より先）にあること。
            seg_lo = min(
                extension_axis_param(segment.p1, ext),
                extension_axis_param(segment.p2, ext),
            )
            seg_hi = max(
                extension_axis_param(segment.p1, ext),
                extension_axis_param(segment.p2, ext),
            )
            if seg_hi < far_param - tolerance:
                continue
            if perp < best_distance:
                best = segment
                best_distance = perp
        if best is None:
            return None
        object_ids.append(best.element_id)
    # 両方の引出線に対象線分があれば、2つの対象線の間の距離が実測長。
    # 寸法線自体がその距離を表すため、寸法線と同じ長さの合成線分を返す。
    return _Segment(
        p1=dimension_line.p1, p2=dimension_line.p2, element_id=object_ids[0]
    )


def _find_measured_line(
    dimension_line: _Segment,
    extensions: List[_Segment],
    segments: List[_Segment],
    font_height: float,
) -> Optional[_Segment]:
    """寸法線に対応する測定対象の線を探す。

    引出線の対象側の端（測定対象に接する端）を通り、寸法線と平行な
    直線を「対象線」とする。その直線の近くにある平行な線分を集め、
    同じ直線上にあるものを連結して「鎖」とみなす。実図面の壁は
    ポリライン（開口で分断）や二重線で描かれるため、1 本の線分では
    寸法区間を覆えないことがある。鎖が寸法区間の半分以上を覆えば
    測定対象とし、実測長は鎖の両端の間隔（寸法区間で切り取ったもの）
    とする。開口の隙間も寸法に含まれる。鎖のうち、寸法区間を最も
    多く覆うものを返す。見つからなければ None。
    """
    # まず、2つの対象線の間の距離を測る寸法（実図面で一般的）を試す。
    # 見つからなければ、平行な壁そのものを測る寸法にフォールバックする。
    between = _find_measured_line_between_objects(
        dimension_line, extensions, segments, font_height
    )
    if between is not None:
        return between
    # 引出線の対象側の端点（寸法線の端点から最も遠い端）。
    far_ends: List[Tuple[float, float]] = []
    for endpoint in (dimension_line.p1, dimension_line.p2):
        for ext in extensions:
            end_distance, _ = _point_to_segment_distance(endpoint, ext)
            if end_distance > max(2.0 * font_height, 0.02 * dimension_line.length):
                continue
            far_end = max(
                (ext.p1, ext.p2),
                key=lambda p: math.hypot(p[0] - endpoint[0], p[1] - endpoint[1]),
            )
            far_ends.append(far_end)
            break
    if not far_ends:
        return None

    tolerance = max(2.0 * font_height, 0.02 * dimension_line.length)
    dx = dimension_line.p2[0] - dimension_line.p1[0]
    dy = dimension_line.p2[1] - dimension_line.p1[1]
    dim_length = math.hypot(dx, dy)
    if dim_length == 0.0:
        return None
    ux, uy = dx / dim_length, dy / dim_length
    vx, vy = -uy, ux

    def projection(point: Tuple[float, float]) -> float:
        return (point[0] - dimension_line.p1[0]) * ux + (point[1] - dimension_line.p1[1]) * uy

    def offset(point: Tuple[float, float]) -> float:
        return (point[0] - dimension_line.p1[0]) * vx + (point[1] - dimension_line.p1[1]) * vy

    # 対象線の垂線方向の位置（寸法線の軸からの距離）。
    target_offsets = [offset(p) for p in far_ends]

    # 候補: 寸法線と平行で、対象線の近くにある線分。区間の中間の線分も
    # 対象になるよう、引出線の端に接していることは求めない。
    candidates = []
    for segment in segments:
        if segment is dimension_line:
            continue
        if _angle_diff_deg(segment.angle_deg, dimension_line.angle_deg) > _PARALLEL_ANGLE_TOL_DEG:
            continue
        off = (offset(segment.p1) + offset(segment.p2)) / 2.0
        if not any(abs(off - target) <= tolerance for target in target_offsets):
            continue
        lo, hi = sorted((projection(segment.p1), projection(segment.p2)))
        candidates.append((lo, hi, off, segment))
    if not candidates:
        return None

    # 同じ直線（垂線方向のずれが許容誤差以内）の線分をグループ化する。
    groups: List[List[Tuple[float, float, float, _Segment]]] = []
    for candidate in sorted(candidates, key=lambda c: c[2]):
        placed = False
        for group in groups:
            if abs(candidate[2] - group[0][2]) <= tolerance:
                group.append(candidate)
                placed = True
                break
        if not placed:
            groups.append([candidate])

    best: Optional[_Segment] = None
    best_covered = 0.0
    best_distance = float("inf")
    for group in groups:
        # 寸法区間で切り取った区間の和集合で、覆われている長さを求める。
        clipped = []
        for lo, hi, _off, _seg in group:
            c_lo, c_hi = max(lo, 0.0), min(hi, dim_length)
            if c_hi > c_lo:
                clipped.append((c_lo, c_hi))
        if not clipped:
            continue
        clipped.sort()
        covered = 0.0
        cur_lo, cur_hi = clipped[0]
        for c_lo, c_hi in clipped[1:]:
            if c_lo <= cur_hi:
                cur_hi = max(cur_hi, c_hi)
            else:
                covered += cur_hi - cur_lo
                cur_lo, cur_hi = c_lo, c_hi
        covered += cur_hi - cur_lo
        span_lo = min(c[0] for c in clipped)
        span_hi = max(c[1] for c in clipped)
        if covered < 0.5 * dim_length:
            continue
        mean_offset = sum(c[2] for c in group) / len(group)
        # 対象線（引出線の端）に最も近い鎖を優先する。二重線の壁では
        # 引出線が接する面の方が正しい測定対象になる。
        obj_distance = min(
            abs(mean_offset - target) for target in target_offsets
        )
        # 覆う長さが最も大きい鎖を選び、同点なら対象点に近いものを選ぶ。
        if covered > best_covered + 1e-9 or (
            abs(covered - best_covered) <= 1e-9 and obj_distance < best_distance
        ):
            best_covered = covered
            best_distance = obj_distance
            p1 = (
                dimension_line.p1[0] + ux * span_lo + vx * mean_offset,
                dimension_line.p1[1] + uy * span_lo + vy * mean_offset,
            )
            p2 = (
                dimension_line.p1[0] + ux * span_hi + vx * mean_offset,
                dimension_line.p1[1] + uy * span_hi + vy * mean_offset,
            )
            longest = max(group, key=lambda c: c[1] - c[0])[3]
            best = _Segment(p1=p1, p2=p2, element_id=longest.element_id)
    return best


def check_dimensions(drawing: Drawing, mm_per_pt: Optional[float] = None) -> List[DimensionCheck]:
    """Drawing 内の寸法を抽出して照合する。

    結果は ``drawing._meta["dimension_checks"]`` にも記録し、ログに出す。
    寸法線の候補が見つからない数値テキスト（部屋番号など）は寸法では
    ないとみなし、結果に含めない。
    """
    if mm_per_pt is None:
        mm_per_pt = float((getattr(drawing, "_meta", {}) or {}).get("mm_per_pt") or 1.0)
    if mm_per_pt <= 0:
        mm_per_pt = 1.0

    segments = _collect_segments(drawing)
    checks: List[DimensionCheck] = []
    counter = 0
    for element in drawing.elements:
        if not isinstance(element, TextElement):
            continue
        value = parse_dimension_value(element.text)
        if value is None:
            continue
        # 部屋番号などの小さな数値は寸法ではない。
        if value < _MIN_DIMENSION_VALUE_MM:
            continue
        dimension_line, confidence, extensions = _find_dimension_line(element, segments)
        if dimension_line is None or confidence < _CANDIDATE_THRESHOLD:
            continue
        counter += 1
        dimension_id = f"DIM{counter:03d}"
        font_height = max(float(element.height or 0.0), 1.0)
        tolerance = max(_REL_TOLERANCE * value, _ABS_TOLERANCE_MM)
        check = DimensionCheck(
            dimension_id=dimension_id,
            value_mm=value,
            dimension_text=element.text,
            status="not_determinable",
            confidence=round(confidence, 2),
            tolerance_mm=round(tolerance, 3),
            dimension_line_id=dimension_line.element_id,
        )
        measured = _find_measured_line(dimension_line, extensions, segments, font_height)
        if measured is not None:
            measured_mm = measured.length
            check.measured_mm = round(measured_mm, 3)
            check.measured_length_pt = round(measured_mm / mm_per_pt, 3)
            check.measured_line_id = measured.element_id
            check.difference_mm = round(measured_mm - value, 3)
        if confidence < _CONFIDENT_THRESHOLD:
            check.status = "to_confirm"
            check.reason = "寸法線の確信度が低いため、要確認です。"
        elif measured is None:
            check.status = "not_determinable"
            check.reason = "測定対象の線が見つからなかったため、照合できません。"
        elif abs(check.difference_mm or 0.0) <= tolerance:
            check.status = "matched"
            check.reason = "実測長が寸法値と一致しています。"
        else:
            check.status = "mismatched"
            check.reason = "実測長が寸法値と一致していません。倍率調整が必要です。"
        checks.append(check)

    meta = getattr(drawing, "_meta", None)
    if meta is None:
        meta = {}
        drawing._meta = meta  # type: ignore[attr-defined]
    meta["dimension_checks"] = [c.to_dict() for c in checks]
    matched = sum(1 for c in checks if c.status == "matched")
    mismatched = sum(1 for c in checks if c.status == "mismatched")
    to_confirm = sum(1 for c in checks if c.status == "to_confirm")
    not_determinable = sum(1 for c in checks if c.status == "not_determinable")
    logger.info(
        "寸法照合: %d 件（一致 %d、不一致 %d、要確認 %d、判定不能 %d）",
        len(checks), matched, mismatched, to_confirm, not_determinable,
    )
    return checks


def calibrate_scale_from_dimension(
    check: DimensionCheck, current_mm_per_pt: float
) -> float:
    """寸法照合の結果から、正しい mm/pt 換算率を計算する。

    寸法値 / 実測長（pt 単位）が新しい換算率になる。測定対象の線が
    見つかっていない照合結果からは計算できないため ValueError を返す。
    """
    if check.measured_length_pt is None or check.measured_length_pt <= 0:
        raise ValueError("測定対象の線が見つかっていないため、換算率を計算できません。")
    if current_mm_per_pt is None or current_mm_per_pt <= 0:
        raise ValueError("現在の換算率が不正です。")
    return check.value_mm / check.measured_length_pt


def calibrate_scale_from_checks(
    checks: List[DimensionCheck],
    current_mm_per_pt: float,
    min_agreeing: int = 3,
    agreement_tolerance: float = 0.05,
) -> Tuple[float, List[DimensionCheck]]:
    """複数の不一致寸法から合意する換算率を求める。

    各寸法の示す換算率（value_mm / measured_length_pt）のうち、
    互いに agreement_tolerance 以内で一致するものが min_agreeing 件以上
    ある場合、その中央値を新しい換算率として返す。合意した寸法の一覧も
    返す。合意がなければ ValueError を返す。1 件だけの寸法から換算率を
    決めると、誤った寸法（実図面で 1116mm/184pt → 6.06mm/pt のような
    外れ値）を信じて図面全体の倍率を壊すため、単独の寸法では調整しない。
    """
    if current_mm_per_pt is None or current_mm_per_pt <= 0:
        raise ValueError("現在の換算率が不正です。")
    implied: List[Tuple[float, DimensionCheck]] = []
    for check in checks:
        if check.measured_length_pt is None or check.measured_length_pt <= 0:
            continue
        if check.value_mm is None or check.value_mm <= 0:
            continue
        implied.append((check.value_mm / check.measured_length_pt, check))
    if not implied:
        raise ValueError(
            "換算率を示す寸法がありません（測定対象の線が見つかっていません）。"
        )
    implied.sort(key=lambda item: item[0])
    # 互いに agreement_tolerance 以内で一致する最大の集団を探す。
    best_cluster: List[Tuple[float, DimensionCheck]] = []
    for i in range(len(implied)):
        cluster = [implied[i]]
        for j in range(i + 1, len(implied)):
            if implied[j][0] <= implied[i][0] * (1.0 + agreement_tolerance):
                cluster.append(implied[j])
            else:
                break
        if len(cluster) > len(best_cluster):
            best_cluster = cluster
    if len(best_cluster) < min_agreeing:
        raise ValueError(
            f"寸法の示す換算率が一致しません（最も近い集団は {len(best_cluster)} 件、"
            f"必要 {min_agreeing} 件）。外れ値の寸法があるか、測定対象の線が"
            "誤っている可能性があります。倍率を手入力で指定してください。"
        )
    scales = sorted(scale for scale, _ in best_cluster)
    if len(scales) % 2 == 1:
        median = scales[len(scales) // 2]
    else:
        median = (scales[len(scales) // 2 - 1] + scales[len(scales) // 2]) / 2.0
    agreeing = [check for _scale, check in best_cluster]
    return median, agreeing


def rescale_drawing(
    drawing: Drawing,
    new_mm_per_pt: float,
    source_check: Optional[DimensionCheck] = None,
) -> float:
    """全要素の座標を新しい換算率に合わせて拡大・縮小する。

    倍率は new / old（old は現在の換算率）。Drawing.scale と
    ``_meta["mm_per_pt"]`` を更新し、``units_source`` を
    ``"calibrated_from_dimension"`` にする。調整前の照合結果は
    古くなるため削除し、再照合が必要な旨を記録する。
    適用した倍率を返す。
    """
    meta = getattr(drawing, "_meta", None)
    if meta is None:
        meta = {}
        drawing._meta = meta  # type: ignore[attr-defined]
    old_mm_per_pt = float(meta.get("mm_per_pt") or drawing.scale or 1.0)
    if old_mm_per_pt <= 0:
        raise ValueError("現在の換算率が不正です。")
    if new_mm_per_pt is None or float(new_mm_per_pt) <= 0:
        raise ValueError("新しい換算率が不正です。")
    new_mm_per_pt = float(new_mm_per_pt)
    factor = new_mm_per_pt / old_mm_per_pt

    def scale_point(point: List[float]) -> List[float]:
        return [float(point[0]) * factor, float(point[1]) * factor]

    for element in drawing.elements:
        if isinstance(element, LineElement):
            element.start = scale_point(element.start)
            element.end = scale_point(element.end)
        elif isinstance(element, PolylineElement):
            element.points = [scale_point(p) for p in element.points]
        elif isinstance(element, TextElement):
            element.insertion_point = scale_point(element.insertion_point)
            if element.bbox:
                element.bbox = [
                    float(element.bbox[0]) * factor,
                    float(element.bbox[1]) * factor,
                    float(element.bbox[2]) * factor,
                    float(element.bbox[3]) * factor,
                ]
            element.height = float(element.height) * factor
        elif isinstance(element, (CircleElement, ArcElement)):
            element.center = scale_point(element.center)
            element.radius = float(element.radius) * factor
        elif isinstance(element, InsertElement):
            element.insert_point = scale_point(element.insert_point)
            element.scale_x = float(element.scale_x) * factor
            element.scale_y = float(element.scale_y) * factor
            element.scale_z = float(element.scale_z) * factor

    calibration: Dict[str, object] = {
        "old_mm_per_pt": old_mm_per_pt,
        "new_mm_per_pt": new_mm_per_pt,
        "factor": factor,
    }
    if source_check is not None:
        calibration["dimension_id"] = source_check.dimension_id
        calibration["dimension_text"] = source_check.dimension_text
        calibration["value_mm"] = source_check.value_mm
        calibration["measured_length_pt"] = source_check.measured_length_pt
    meta["mm_per_pt"] = new_mm_per_pt
    meta["units_source"] = "calibrated_from_dimension"
    meta["calibration"] = calibration
    meta["dimension_checks"] = []
    meta["calibration_note"] = (
        "倍率調整により以前の照合結果は古くなったため削除しました。"
        "寸法照合をやり直してください。"
    )
    drawing.scale = new_mm_per_pt
    logger.info(
        "倍率調整: %.6f mm/pt -> %.6f mm/pt（倍率 %.6f）",
        old_mm_per_pt, new_mm_per_pt, factor,
    )
    return factor
