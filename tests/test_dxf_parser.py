"""
tests/test_dxf_parser.py
DxfParser の実装テスト。テスト用DXFファイルを使って動作確認を行う。
"""

import os
import pytest
from core.parser.dxf_parser import DxfParser
from core.models.drawing import Drawing, LineElement, PolylineElement, TextElement

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def _data_path(filename: str) -> str:
    return os.path.join(DATA_DIR, filename)


def test_dxf_parser_invalid_file():
    """存在しないファイルを渡してもクラッシュしないこと。"""
    parser = DxfParser()
    drawing = parser.parse("non_existent_file.dxf")
    assert isinstance(drawing, Drawing)
    assert len(drawing.elements) == 0


def test_dxf_parser_sample_01_rect():
    """Test 01 (矩形 LWPOLYLINE) のパース検証"""
    filepath = _data_path("sample_01_rect.dxf")
    if not os.path.exists(filepath):
        pytest.skip(f"テストファイルが存在しません: {filepath}")
    parser = DxfParser()
    drawing = parser.parse(filepath)
    assert isinstance(drawing, Drawing)
    assert len(drawing.elements) == 1
    poly = drawing.elements[0]
    assert isinstance(poly, PolylineElement)
    assert poly.is_closed is True
    assert len(poly.points) == 4


def test_dxf_parser_sample_02_multi_rect():
    """Test 02 (複数矩形) のパース検証"""
    filepath = _data_path("sample_02_multi_rect.dxf")
    if not os.path.exists(filepath):
        pytest.skip(f"テストファイルが存在しません: {filepath}")
    parser = DxfParser()
    drawing = parser.parse(filepath)
    assert isinstance(drawing, Drawing)
    assert len(drawing.elements) == 2
    for elem in drawing.elements:
        assert isinstance(elem, PolylineElement)


def test_dxf_parser_sample_03_lines_arcs():
    """Test 03 (LINE + LWPOLYLINE + ARC + CIRCLE) のパース検証"""
    filepath = _data_path("sample_03_lines_arcs.dxf")
    if not os.path.exists(filepath):
        pytest.skip(f"テストファイルが存在しません: {filepath}")
    parser = DxfParser()
    drawing = parser.parse(filepath)
    assert isinstance(drawing, Drawing)
    assert len(drawing.elements) == 5

    types = [e.element_type for e in drawing.elements]
    assert "LINE" in types
    assert "POLYLINE" in types
    assert "CIRCLE" in types
    assert "ARC" in types


def test_dxf_parser_sample_04_text():
    """Test 04 (TEXT + MTEXT) のパース検証"""
    filepath = _data_path("sample_04_text.dxf")
    if not os.path.exists(filepath):
        pytest.skip(f"テストファイルが存在しません: {filepath}")
    parser = DxfParser()
    drawing = parser.parse(filepath)
    assert isinstance(drawing, Drawing)
    assert len(drawing.elements) == 2
    for elem in drawing.elements:
        assert isinstance(elem, TextElement)
        assert len(elem.text) > 0


def test_dxf_parser_layer_info():
    """レイヤー情報の取得検証"""
    filepath = _data_path("sample_03_lines_arcs.dxf")
    if not os.path.exists(filepath):
        pytest.skip(f"テストファイルが存在しません: {filepath}")
    parser = DxfParser()
    layers = parser.get_layer_info(filepath)
    assert isinstance(layers, list)
    layer_names = [l["name"] for l in layers]
    assert "STRUCTURE" in layer_names
    assert "FURNITURE" in layer_names

