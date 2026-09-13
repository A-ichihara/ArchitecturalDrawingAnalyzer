from abc import ABC, abstractmethod
from core.models.drawing import Drawing

class IDrawingParser(ABC):
    """
    各種図面ファイル（DXF, PDF, 画像）を解析し、システム共通の Drawing モデルへ変換する
    パーサーのインターフェースです。
    """
    @abstractmethod
    def parse(self, file_path: str, **kwargs) -> Drawing:
        """
        指定された図面ファイルを解析して Drawing オブジェクトを返します。
        
        Args:
            file_path: 解析対象ファイルのパス
            **kwargs: 縮尺、解像度、オフセットなどのパーサー固有のオプション
        Returns:
            共通データ構造化された Drawing オブジェクト
        """
        pass
