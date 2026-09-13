from core.parser.interface import IDrawingParser
from core.models.drawing import Drawing
import os

class ImageParser(IDrawingParser):
    """
    画像ファイル（PNG, JPEGなど）用のパーサーです。
    将来的にOpenCVなどの画像処理ライブラリやOCRエンジンと連携し、壁線や文字の抽出・ポリゴン化を行います。
    """
    def parse(self, file_path: str, **kwargs) -> Drawing:
        scale = kwargs.get("scale", 100.0)
        units = kwargs.get("units", "px")
        drawing_id = os.path.basename(file_path).split('.')[0]
        
        # Phase 0 スタブ実装
        return Drawing(
            drawing_id=drawing_id,
            file_name=os.path.basename(file_path),
            file_type="image",
            scale=scale,
            units=units,
            elements=[]
        )
