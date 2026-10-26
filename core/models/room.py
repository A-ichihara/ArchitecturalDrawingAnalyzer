from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional

@dataclass
class Room:
    """部屋情報を表すデータクラス。将来的な換気計算や設備設計データとの連携を考慮した設計です。"""
    room_id: str
    room_name: str
    area_m2: float
    boundary: List[List[float]] = field(default_factory=list)  # 境界ポリゴン [[x1, y1], [x2, y2], ...]
    wall_type: str = "unknown"  # "centerline" (壁芯), "inner" (内法), "outer" (外法), "unknown" (未判定)
    confidence: float = 0.0  # 解析結果の信頼度 (0.0 - 1.0)。未判定の既定値は 0.0
    properties: Dict[str, Any] = field(default_factory=dict)  # 将来の拡張用属性

    # 便利プロパティ（将来追加される天井高や容積などへのアクセス用ヘルパー）
    @property
    def ceiling_height(self) -> Optional[float]:
        return self.properties.get("ceiling_height")

    @property
    def volume(self) -> Optional[float]:
        return self.properties.get("volume")

    @property
    def occupants(self) -> Optional[int]:
        return self.properties.get("occupants")

    @property
    def required_ventilation(self) -> Optional[float]:
        return self.properties.get("required_ventilation")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Room':
        d = data.copy()
        return cls(**d)
