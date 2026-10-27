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

# 寸法線の候補とする直線の最小長（mm）。これより短い線は寸法線にしない。
_MIN_DIMENSION_LINE_LENGTH_MM = 100.0

# 寸法線の方向の許容誤差（度）。水平・垂直からこの範囲内なら軸平行とみなす。
_AXIS_ANGLE_TOL_DEG = 2.0
# 平行・直交の判定の許容誤差（度）。
_PARALLEL_ANGLE_TOL_DEG = 2.0
_PERPENDICULAR_ANGLE_TOL_DEG = 5.0

_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９．，", "0123456789.,")
_DIMENSION_VALUE_RE = re.compile(r"^\d+(\.\d+)?$")


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
        if segment.length < _MIN_DIMENSION_LINE_LENGTH_MM:
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
                if not (font_height <= other.length <= 0.35 * segment.length):
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


def _find_measured_line(
    dimension_line: _Segment,
    extensions: List[_Segment],
    segments: List[_Segment],
    font_height: float,
) -> Optional[_Segment]:
    """寸法線に対応する測定対象の線を探す。

    引出線の、寸法線から最も遠い端（測定対象に接する端）の近くを通り、
    寸法線と平行で、寸法線の区間と半分以上重なる線のうち、寸法線に
    最も近いものを返す。見つからなければ None。
    """
    # 引出線の測定対象側の端点（寸法線の端点から最も遠い端）。
    object_points: List[Tuple[float, float]] = []
    for endpoint in (dimension_line.p1, dimension_line.p2):
        for ext in extensions:
            end_distance, _ = _point_to_segment_distance(endpoint, ext)
            if end_distance > max(2.0 * font_height, 0.02 * dimension_line.length):
                continue
            far_end = max(
                (ext.p1, ext.p2),
                key=lambda p: math.hypot(p[0] - endpoint[0], p[1] - endpoint[1]),
            )
            object_points.append(far_end)
            break
    if not object_points:
        return None

    tolerance = max(2.0 * font_height, 0.02 * dimension_line.length)
    best: Optional[_Segment] = None
    best_distance = float("inf")
    for segment in segments:
        if segment is dimension_line:
            continue
        if _angle_diff_deg(segment.angle_deg, dimension_line.angle_deg) > _PARALLEL_ANGLE_TOL_DEG:
            continue
        if abs(segment.length - dimension_line.length) > 0.5 * dimension_line.length:
            continue
        # 測定対象の線は引出線の対象側の端点の近くを通ること。
        if not any(
            _point_to_segment_distance(point, segment)[0] <= tolerance
            for point in object_points
        ):
            continue
        # 寸法線の区間との重なりが半分以上あること。
        overlap = _projection_overlap(dimension_line, segment)
        if overlap < 0.5 * dimension_line.length:
            continue
        distance, _ = _point_to_segment_distance(dimension_line.midpoint, segment)
        if distance < best_distance:
            best = segment
            best_distance = distance
    return best


def _projection_overlap(a: _Segment, b: _Segment) -> float:
    """2 つの平行な線分の、a の方向への射影の重なり長さを返す。"""
    dx = a.p2[0] - a.p1[0]
    dy = a.p2[1] - a.p1[1]
    length = math.hypot(dx, dy)
    if length == 0.0:
        return 0.0
    ux, uy = dx / length, dy / length

    def param(point: Tuple[float, float]) -> float:
        return (point[0] - a.p1[0]) * ux + (point[1] - a.p1[1]) * uy

    a_lo, a_hi = 0.0, length
    b_lo, b_hi = sorted((param(b.p1), param(b.p2)))
    return max(0.0, min(a_hi, b_hi) - max(a_lo, b_lo))


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
