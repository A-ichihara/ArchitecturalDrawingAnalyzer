import pytest
from core.parser.interface import IDrawingParser
from core.parser.dxf_parser import DxfParser
from core.parser.pdf_parser import PdfParser
from core.parser.image_parser import ImageParser
from core.models.drawing import Drawing

def test_parsers_instantiation():
    dxf_parser = DxfParser()
    pdf_parser = PdfParser()
    img_parser = ImageParser()
    
    assert isinstance(dxf_parser, IDrawingParser)
    assert isinstance(pdf_parser, IDrawingParser)
    assert isinstance(img_parser, IDrawingParser)

def test_dxf_parser_stub():
    dxf_parser = DxfParser()
    drawing = dxf_parser.parse("dummy_path/sample_floor_plan.dxf", scale=100.0, units="mm")
    
    assert isinstance(drawing, Drawing)
    assert drawing.drawing_id == "sample_floor_plan"
    assert drawing.file_type == "dxf"
    assert drawing.scale == 100.0
    assert drawing.units == "mm"
    # ファイルが存在しない場合はアプリがクラッシュせず空の要素リストを返すこと
    assert len(drawing.elements) == 0

def test_pdf_parser_stub():
    pdf_parser = PdfParser()
    drawing = pdf_parser.parse("dummy_path/sample_floor_plan.pdf", scale=100.0)
    
    assert isinstance(drawing, Drawing)
    assert drawing.drawing_id == "sample_floor_plan"
    assert drawing.file_type == "pdf"
    assert len(drawing.elements) == 0

def test_image_parser_stub():
    img_parser = ImageParser()
    drawing = img_parser.parse("dummy_path/sample_floor_plan.png", scale=100.0)
    
    assert isinstance(drawing, Drawing)
    assert drawing.drawing_id == "sample_floor_plan"
    assert drawing.file_type == "image"
    assert len(drawing.elements) == 0
