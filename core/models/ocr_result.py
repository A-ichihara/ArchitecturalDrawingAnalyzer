from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any

@dataclass
class OCRResult:
    """画像やPDFから文字認識した結果を表現するデータクラス"""
    text: str
    bbox: List[float]  # バウンディングボックス [x_min, y_min, x_max, y_max] (画像または共通座標系)
    confidence: float  # 認識信頼度 (0.0 - 1.0)
    properties: Dict[str, Any] = field(default_factory=dict)  # 追加属性 (フォント情報、回転角など)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OCRResult':
        d = data.copy()
        return cls(**d)
