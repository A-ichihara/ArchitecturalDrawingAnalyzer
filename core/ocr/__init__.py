"""
core.ocr
OCRエンジンの抽象化レイヤーを提供します。Tesseract, PaddleOCR, EasyOCRなどを差し替え可能です。
"""

from .interface import IOcrEngine, TesseractOcrEngine, PaddleOcrEngine, EasyOcrEngine

__all__ = [
    "IOcrEngine",
    "TesseractOcrEngine",
    "PaddleOcrEngine",
    "EasyOcrEngine",
]
