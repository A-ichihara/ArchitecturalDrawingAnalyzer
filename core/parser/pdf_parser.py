from core.parser.interface import IDrawingParser
from core.models.drawing import Drawing
import os

class PdfParser(IDrawingParser):
    """
    PDF（ベクトルPDF）ファイル用のパーサーです。
    将来的に PyMuPDF や pdfplumber を使用して、PDF内のベクトル要素や文字テキスト情報を直接抽出します。
    また、画像PDFの場合はImageParserへの変換処理なども中継します。
    """
    def parse(self, file_path: str, **kwargs) -> Drawing:
        scale = kwargs.get("scale", 100.0)
        units = kwargs.get("units", "mm")
        drawing_id = os.path.basename(file_path).split('.')[0]
        
        # Phase 0 スタブ実装
        return Drawing(
            drawing_id=drawing_id,
            file_name=os.path.basename(file_path),
            file_type="pdf",
            scale=scale,
            units=units,
            elements=[]
        )
