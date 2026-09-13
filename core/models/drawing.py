from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional

@dataclass
class DrawingElement:
    """図面を構成する基本グラフィック要素の基底クラス"""
    element_id: str
    element_type: str  # "LINE", "POLYLINE", "TEXT", "CIRCLE", "ARC"
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
        elif element_type == "TEXT":
            return TextElement.from_dict(data)
        elif element_type == "CIRCLE":
            return CircleElement.from_dict(data)
        elif element_type == "ARC":
            return ArcElement.from_dict(data)
        
        # 該当がない場合は基底クラスを返す
        d = data.copy()
        return cls(**d)

@dataclass
class LineElement(DrawingElement):
    """線分要素"""
    start: List[float] = field(default_factory=lambda: [0.0, 0.0])  # [x, y] または [x, y, z]
    end: List[float] = field(default_factory=lambda: [0.0, 0.0])

    def __post_init__(self):
        self.element_type = "LINE"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LineElement':
        d = data.copy()
        return cls(**d)

@dataclass
class PolylineElement(DrawingElement):
    """ポリライン（連続線）要素"""
    points: List[List[float]] = field(default_factory=list)  # [[x1, y1], [x2, y2], ...]
    is_closed: bool = False

    def __post_init__(self):
        self.element_type = "POLYLINE"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PolylineElement':
        d = data.copy()
        return cls(**d)

@dataclass
class TextElement(DrawingElement):
    """文字要素"""
    text: str = ""
    insertion_point: List[float] = field(default_factory=lambda: [0.0, 0.0])  # [x, y]
    height: float = 2.5
    rotation: float = 0.0  # 角度 (度数法)
    bbox: Optional[List[float]] = None  # [x_min, y_min, x_max, y_max]

    def __post_init__(self):
        self.element_type = "TEXT"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TextElement':
        d = data.copy()
        return cls(**d)

@dataclass
class CircleElement(DrawingElement):
    """円要素"""
    center: List[float] = field(default_factory=lambda: [0.0, 0.0])  # [x, y]
    radius: float = 0.0

    def __post_init__(self):
        self.element_type = "CIRCLE"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CircleElement':
        d = data.copy()
        return cls(**d)

@dataclass
class ArcElement(DrawingElement):
    """円弧要素"""
    center: List[float] = field(default_factory=lambda: [0.0, 0.0])  # [x, y]
    radius: float = 0.0
    start_angle: float = 0.0  # 開始角度 (度数法)
    end_angle: float = 0.0    # 終了角度 (度数法)

    def __post_init__(self):
        self.element_type = "ARC"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ArcElement':
        d = data.copy()
        return cls(**d)

@dataclass
class Drawing:
    """図面全体のデータ表現"""
    drawing_id: str
    file_name: str
    file_type: str  # "dxf", "pdf", "image" など
    scale: float = 1.0  # 縮尺 (例: 1/100図面なら 100)
    units: str = "mm"   # "mm", "m", "px", "pt"
    elements: List[DrawingElement] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "drawing_id": self.drawing_id,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "scale": self.scale,
            "units": self.units,
            "elements": [e.to_dict() for e in self.elements]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Drawing':
        elements_data = data.get("elements", [])
        elements = [DrawingElement.from_dict(e) for e in elements_data]
        return cls(
            drawing_id=data["drawing_id"],
            file_name=data["file_name"],
            file_type=data["file_type"],
            scale=data.get("scale", 1.0),
            units=data.get("units", "mm"),
            elements=elements
        )
