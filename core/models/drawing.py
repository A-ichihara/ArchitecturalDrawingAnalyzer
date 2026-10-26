from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional


# ---------------------------------------------------------------------------
# 基底クラス
# ---------------------------------------------------------------------------

@dataclass
class DrawingElement:
    """図面を構成する基本グラフィック要素の基底クラス"""
    element_id: str
    element_type: str  # "LINE", "POLYLINE", "TEXT", "MTEXT", "CIRCLE", "ARC", "INSERT"
    layer: str = "0"
    color: Optional[int] = None
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DrawingElement':
        element_type = data.get("element_type")
        if element_type == "LINE":
            return LineElement.from_dict(data)
        elif element_type == "POLYLINE":
            return PolylineElement.from_dict(data)
        elif element_type in ("TEXT", "MTEXT"):
            return TextElement.from_dict(data)
        elif element_type == "CIRCLE":
            return CircleElement.from_dict(data)
        elif element_type == "ARC":
            return ArcElement.from_dict(data)
        elif element_type == "INSERT":
            return InsertElement.from_dict(data)

        # 該当がない場合は基底クラスを返す
        d = data.copy()
        return cls(**d)


# ---------------------------------------------------------------------------
# LINE
# ---------------------------------------------------------------------------

@dataclass
class LineElement(DrawingElement):
    """線分要素。始点・終点・長さ・角度を保持する。"""
    start: List[float] = field(default_factory=lambda: [0.0, 0.0])  # [x, y]
    end: List[float] = field(default_factory=lambda: [0.0, 0.0])    # [x, y]

    def __post_init__(self):
        self.element_type = "LINE"

    @property
    def length(self) -> float:
        """線分の長さ（決定論的計算）"""
        dx = self.end[0] - self.start[0]
        dy = self.end[1] - self.start[1]
        return math.sqrt(dx * dx + dy * dy)

    @property
    def angle(self) -> float:
        """始点→終点の角度（度数法、0〜360）"""
        dx = self.end[0] - self.start[0]
        dy = self.end[1] - self.start[1]
        return math.degrees(math.atan2(dy, dx)) % 360.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LineElement':
        d = data.copy()
        return cls(**d)


# ---------------------------------------------------------------------------
# POLYLINE / LWPOLYLINE
# ---------------------------------------------------------------------------

@dataclass
class PolylineElement(DrawingElement):
    """ポリライン（連続線）要素。頂点列・閉合・bulge を保持する。"""
    points: List[List[float]] = field(default_factory=list)   # [[x1,y1], [x2,y2], ...]
    is_closed: bool = False
    # bulge_list は LWPOLYLINEの曲線情報（0=直線、±1=半円）
    # points と同じ長さ。非対応時は空リスト。
    bulge_list: List[float] = field(default_factory=list)

    def __post_init__(self):
        self.element_type = "POLYLINE"

    @property
    def length(self) -> float:
        """ポリラインの全長（bulgeで表される円弧区間も含めて計算）。"""
        if len(self.points) < 2:
            return 0.0

        total = 0.0
        segment_count = len(self.points) if self.is_closed else len(self.points) - 1
        for i in range(segment_count):
            start = self.points[i]
            end = self.points[(i + 1) % len(self.points)]
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            chord_length = math.hypot(dx, dy)
            bulge = self.bulge_list[i] if i < len(self.bulge_list) else 0.0

            if chord_length == 0.0 or abs(bulge) < 1e-12:
                total += chord_length
                continue

            included_angle = 4.0 * math.atan(abs(bulge))
            radius = chord_length * (1.0 + bulge * bulge) / (4.0 * abs(bulge))
            total += radius * included_angle

        return total

    @property
    def vertex_count(self) -> int:
        """頂点数"""
        return len(self.points)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PolylineElement':
        d = data.copy()
        # 後方互換: bulge_list がない場合はデフォルト空リスト
        d.setdefault("bulge_list", [])
        return cls(**d)


# ---------------------------------------------------------------------------
# TEXT / MTEXT
# ---------------------------------------------------------------------------

@dataclass
class TextElement(DrawingElement):
    """文字要素（TEXT / MTEXT 共通）。element_type で区別する。"""
    text: str = ""
    insertion_point: List[float] = field(default_factory=lambda: [0.0, 0.0])  # [x, y]
    height: float = 2.5
    rotation: float = 0.0       # 角度（度数法）
    style: str = ""             # DXFテキストスタイル名
    bbox: Optional[List[float]] = None  # [x_min, y_min, x_max, y_max]
    # element_type は "TEXT" または "MTEXT" をパーサーが設定する

    def __post_init__(self):
        # 不正な element_type が来た場合のみデフォルトに戻す
        if self.element_type not in ("TEXT", "MTEXT"):
            self.element_type = "TEXT"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TextElement':
        d = data.copy()
        d.setdefault("style", "")
        return cls(**d)


# ---------------------------------------------------------------------------
# CIRCLE
# ---------------------------------------------------------------------------

@dataclass
class CircleElement(DrawingElement):
    """円要素"""
    center: List[float] = field(default_factory=lambda: [0.0, 0.0])  # [x, y]
    radius: float = 0.0

    def __post_init__(self):
        self.element_type = "CIRCLE"

    @property
    def diameter(self) -> float:
        return self.radius * 2.0

    @property
    def circumference(self) -> float:
        return 2.0 * math.pi * self.radius

    @property
    def area(self) -> float:
        return math.pi * self.radius * self.radius

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CircleElement':
        d = data.copy()
        return cls(**d)


# ---------------------------------------------------------------------------
# ARC
# ---------------------------------------------------------------------------

@dataclass
class ArcElement(DrawingElement):
    """円弧要素"""
    center: List[float] = field(default_factory=lambda: [0.0, 0.0])  # [x, y]
    radius: float = 0.0
    start_angle: float = 0.0  # 開始角度（度数法）
    end_angle: float = 0.0    # 終了角度（度数法）

    def __post_init__(self):
        self.element_type = "ARC"

    @property
    def span_angle(self) -> float:
        """円弧の中心角（度数法、正値）"""
        span = self.end_angle - self.start_angle
        if span <= 0:
            span += 360.0
        return span

    @property
    def arc_length(self) -> float:
        """弧長"""
        return self.radius * math.radians(self.span_angle)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ArcElement':
        d = data.copy()
        return cls(**d)


# ---------------------------------------------------------------------------
# INSERT（BLOCK参照）
# ---------------------------------------------------------------------------

@dataclass
class InsertElement(DrawingElement):
    """
    INSERT エンティティ（ブロック参照）。
    展開できる参照はパーサーがブロック内容を図形要素に展開する。
    展開できない参照（未定義ブロック等）のみ InsertElement として残り、
    ビューアではマーカー表示される。
    """
    block_name: str = ""
    insert_point: List[float] = field(default_factory=lambda: [0.0, 0.0])  # [x, y]
    rotation: float = 0.0         # 回転角度（度数法）
    scale_x: float = 1.0
    scale_y: float = 1.0
    scale_z: float = 1.0

    def __post_init__(self):
        self.element_type = "INSERT"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'InsertElement':
        d = data.copy()
        d.setdefault("block_name", "")
        d.setdefault("insert_point", [0.0, 0.0])
        d.setdefault("rotation", 0.0)
        d.setdefault("scale_x", 1.0)
        d.setdefault("scale_y", 1.0)
        d.setdefault("scale_z", 1.0)
        return cls(**d)


# ---------------------------------------------------------------------------
# Drawing（図面全体）
# ---------------------------------------------------------------------------

@dataclass
class Drawing:
    """図面全体のデータ表現"""
    drawing_id: str
    file_name: str
    file_type: str   # "dxf", "pdf", "image" など
    scale: float = 1.0
    units: str = "mm"
    elements: List[DrawingElement] = field(default_factory=list)

    def get_element_by_id(self, element_id: str) -> Optional[DrawingElement]:
        """要素IDから図面要素を検索する。見つからない場合はNone。"""
        return next((element for element in self.elements if element.element_id == element_id), None)

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "drawing_id": self.drawing_id,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "scale": self.scale,
            "units": self.units,
            "elements": [e.to_dict() for e in self.elements],
            # 解析メタデータ（単位の根拠・未対応要素など）。動的属性 _meta
            # として付与されるが、保存・復元時に失われないよう含める。
            "meta": dict(getattr(self, "_meta", {}) or {}),
        }
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Drawing':
        elements_data = data.get("elements", [])
        elements = [DrawingElement.from_dict(e) for e in elements_data]
        drawing = cls(
            drawing_id=data["drawing_id"],
            file_name=data["file_name"],
            file_type=data["file_type"],
            scale=data.get("scale", 1.0),
            units=data.get("units", "mm"),
            elements=elements,
        )
        drawing._meta = dict(data.get("meta", {}) or {})  # type: ignore[attr-defined]
        return drawing
