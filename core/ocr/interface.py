from abc import ABC, abstractmethod
from typing import List, Dict, Any
from core.models.ocr_result import OCRResult
import os

class IOcrEngine(ABC):
    """
    OCRエンジンの共通インターフェースです。
    画像内の文字データを認識し、共通の OCRResult モデルリストとして返します。
    """
    @abstractmethod
    def ocr_image(self, image_path: str, **kwargs) -> List[OCRResult]:
        """
        画像ファイルから文字を認識します。
        
        Args:
            image_path: 画像ファイルのパス
            **kwargs: 言語設定やパラメータオプション
        Returns:
            OCRResult オブジェクトのリスト
        """
        pass


class TesseractOcrEngine(IOcrEngine):
    """
    Tesseract OCR 向けのラッパーラッパー/スタブ実装。
    """
    def ocr_image(self, image_path: str, **kwargs) -> List[OCRResult]:
        # Tesseractは標準で "jpn" (日本語) を指定してローカルで動かせます。
        # Phase 0ではインターフェース確認用のダミーデータを返します。
        lang = kwargs.get("lang", "jpn")
        
        # スタブ用のダミーOCR結果
        results = [
            OCRResult(
                text="事務室",
                bbox=[100.0, 100.0, 300.0, 150.0],
                confidence=0.92,
                properties={"engine": "Tesseract", "lang": lang}
            ),
            OCRResult(
                text="A=25.5㎡",
                bbox=[100.0, 160.0, 320.0, 200.0],
                confidence=0.88,
                properties={"engine": "Tesseract", "lang": lang}
            )
        ]
        return results


class PaddleOcrEngine(IOcrEngine):
    """
    PaddleOCR 向けのラッパー/スタブ実装。
    縦書きや横書きの混在する日本語建築図面で高い認識精度を誇ります。
    """
    def ocr_image(self, image_path: str, **kwargs) -> List[OCRResult]:
        # Phase 0ではインターフェース確認用のダミーデータを返します。
        results = [
            OCRResult(
                text="会議室",
                bbox=[500.0, 200.0, 700.0, 250.0],
                confidence=0.97,
                properties={"engine": "PaddleOCR"}
            )
        ]
        return results


class EasyOcrEngine(IOcrEngine):
    """
    EasyOCR 向けのラッパー/スタブ実装。
    """
    def ocr_image(self, image_path: str, **kwargs) -> List[OCRResult]:
        # Phase 0ではインターフェース確認用のダミーデータを返します。
        results = [
            OCRResult(
                text="休憩室",
                bbox=[800.0, 300.0, 950.0, 350.0],
                confidence=0.91,
                properties={"engine": "EasyOCR"}
            )
        ]
        return results
