from abc import ABC, abstractmethod
from typing import List, Dict, Any

class IAiEngine(ABC):
    """
    意味的判定（部屋名の標準化・判定、解析信頼度の判定、OCR誤字補正など）
    を行うAIエンジンのインターフェースです。
    AIエンジンが無効な場合でもアプリの基本機能が動作するように設計します。
    """
    @abstractmethod
    def classify_room_name(self, name_candidate: str) -> Dict[str, Any]:
        """
        図面から検出された曖昧な部屋名から、標準的な部屋カテゴリ（用途）を推論します。
        例: "ミーティングA" -> {"standard_name": "会議室", "confidence": 0.95}
        """
        pass

    @abstractmethod
    def validate_analysis_confidence(self, room_data: Dict[str, Any]) -> float:
        """
        自動解析された部屋領域情報（面積や形状）の妥当性や信頼度をAIによって評価します。
        """
        pass

    @abstractmethod
    def is_enabled(self) -> bool:
        """AIエンジンが有効化されているかどうかを返します。"""
        pass


class NullAiEngine(IAiEngine):
    """
    AIエンジンを無効化した状態で動作するルールベース/ダミーエンジン。
    セキュリティ上の理由やオフライン・省リソース環境でのフォールバックとして利用します。
    """
    def classify_room_name(self, name_candidate: str) -> Dict[str, Any]:
        # 単純な前方一致・後方一致や完全一致などのルールベースで返す
        cleaned = name_candidate.strip()
        standard_name = cleaned
        
        # 簡易的な静的マッピング例
        mapping = {
            "会議": "会議室",
            "ミーティング": "会議室",
            "打合せ": "会議室",
            "事務": "事務室",
            "オフィス": "事務室",
            "トイレ": "便所",
            "WC": "便所",
            "リフレッシュ": "休憩室",
            "食堂": "休憩室"
        }
        
        for k, v in mapping.items():
            if k in cleaned:
                standard_name = v
                break
                
        return {
            "standard_name": standard_name,
            "confidence": 1.0,
            "notes": "Rules-based fallback mapping (AI disabled)"
        }

    def validate_analysis_confidence(self, room_data: Dict[str, Any]) -> float:
        # AI無効時は常に 1.0（あるいは基本的なルール評価による値）を返す
        return 1.0

    def is_enabled(self) -> bool:
        return False


class LocalAiEngine(IAiEngine):
    """
    ローカル環境で動作するAIモデル（Llama.cpp, ONNXモデルなど）を使用するAIエンジン。
    図面データを外部に送信しないセキュリティ要件を満たすために将来実装されます。
    """
    def classify_room_name(self, name_candidate: str) -> Dict[str, Any]:
        # 将来のローカルLLM呼び出し等の処理
        return {
            "standard_name": name_candidate,
            "confidence": 0.0,
            "notes": "LocalAI stub"
        }

    def validate_analysis_confidence(self, room_data: Dict[str, Any]) -> float:
        return 0.0

    def is_enabled(self) -> bool:
        return True
