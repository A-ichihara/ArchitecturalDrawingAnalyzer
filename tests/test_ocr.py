import pytest
from core.ocr.interface import IOcrEngine, TesseractOcrEngine, PaddleOcrEngine, EasyOcrEngine
from core.models.ocr_result import OCRResult

def test_ocr_engines_instantiation():
    tesseract = TesseractOcrEngine()
    paddle = PaddleOcrEngine()
    easy = EasyOcrEngine()
    
    assert isinstance(tesseract, IOcrEngine)
    assert isinstance(paddle, IOcrEngine)
    assert isinstance(easy, IOcrEngine)

def test_ocr_engines_stub_returns():
    # Tesseract
    tesseract = TesseractOcrEngine()
    res_tess = tesseract.ocr_image("dummy_path/floor_plan.png", lang="jpn")
    assert len(res_tess) == 2
    assert isinstance(res_tess[0], OCRResult)
    assert res_tess[0].text == "事務室"
    assert res_tess[0].confidence == 0.92
    assert res_tess[1].text == "A=25.5㎡"
    
    # PaddleOCR
    paddle = PaddleOcrEngine()
    res_paddle = paddle.ocr_image("dummy_path/floor_plan.png")
    assert len(res_paddle) == 1
    assert isinstance(res_paddle[0], OCRResult)
    assert res_paddle[0].text == "会議室"
    assert res_paddle[0].confidence == 0.97
    
    # EasyOCR
    easy = EasyOcrEngine()
    res_easy = easy.ocr_image("dummy_path/floor_plan.png")
    assert len(res_easy) == 1
    assert isinstance(res_easy[0], OCRResult)
    assert res_easy[0].text == "休憩室"
    assert res_easy[0].confidence == 0.91
