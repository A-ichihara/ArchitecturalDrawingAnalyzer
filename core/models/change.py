from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional

@dataclass
class Change:
    """図面差分（新旧図面比較結果）を表現するデータクラス"""
    change_id: str
    type: str  # "element_added", "element_deleted", "element_moved", "element_modified", "wall_moved", "text_changed" など
    location: List[float] = field(default_factory=list)  # 代表座標 [x, y] または 矩形領域 [x_min, y_min, x_max, y_max]
    old_data: Dict[str, Any] = field(default_factory=dict)  # 変更前の要素データ
    new_data: Dict[str, Any] = field(default_factory=dict)  # 変更後の要素データ
    confidence: float = 1.0  # 差分検出の信頼度 (0.0 - 1.0)
    properties: Dict[str, Any] = field(default_factory=dict)  # その他メタデータ用

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Change':
        d = data.copy()
        return cls(**d)
