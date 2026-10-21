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

def test_dxf_text_is_associated_with_room_after_real_parse(tmp_path):
    """DXF parsing and geometric room-label association work together."""
    import ezdxf
    from core.analyzer.room_detector import (
        associate_room_names,
        detect_closed_polyline_room_candidates,
    )

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4  # millimetres
    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(0, 0), (5000, 0), (5000, 4000), (0, 4000)],
        close=True,
        dxfattribs={"layer": "ROOM_BOUNDARY"},
    )
    msp.add_text(
        "事務室",
        dxfattribs={"insert": (2500, 2000), "height": 250, "layer": "ROOM_LABELS"},
    )
    path = tmp_path / "room_label_text.dxf"
    doc.saveas(path)

    drawing = DxfParser().parse(str(path))
    rooms = detect_closed_polyline_room_candidates(drawing)
    associated = associate_room_names(drawing, rooms)

    assert drawing.units == "mm"
    assert len(associated) == 1
    assert associated[0].area_m2 == pytest.approx(20.0)
    assert associated[0].room_name == "事務室"
    assert associated[0].properties["room_name_source_element_id"].startswith("TEXT_")


def test_dxf_mtext_paragraph_is_normalized_before_room_association(tmp_path):
    """MTEXT paragraph breaks should not prevent a Japanese room label match."""
    import ezdxf
    from core.analyzer.room_detector import (
        associate_room_names,
        detect_closed_polyline_room_candidates,
    )

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(0, 0), (5000, 0), (5000, 4000), (0, 4000)],
        close=True,
        dxfattribs={"layer": "ROOM_BOUNDARY"},
    )
    msp.add_mtext(
        "会議室\\P（受付）",
        dxfattribs={"insert": (2500, 2000), "char_height": 250, "layer": "ROOM_LABELS"},
    )
    path = tmp_path / "room_label_mtext.dxf"
    doc.saveas(path)

    drawing = DxfParser().parse(str(path))
    rooms = detect_closed_polyline_room_candidates(drawing)
    associated = associate_room_names(drawing, rooms)

    assert len(associated) == 1
    assert associated[0].room_name == "会議室 （受付）"
    assert associated[0].properties["room_name_source_element_id"].startswith("MTEXT_")

@pytest.mark.parametrize(
    ("insunits", "expected_units"),
    [(1, "in"), (2, "ft"), (4, "mm"), (5, "cm"), (6, "m")],
)
def test_dxf_parser_infers_supported_insunits(tmp_path, insunits, expected_units):
    import ezdxf

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = insunits
    doc.modelspace().add_line((0, 0), (1000, 0))
    path = tmp_path / f"units_{insunits}.dxf"
    doc.saveas(path)

    drawing = DxfParser().parse(str(path))

    assert drawing.units == expected_units
    assert drawing._meta["units_source"] == "dxf_insunits"


def test_dxf_parser_explicit_units_override_insunits(tmp_path):
    import ezdxf

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6  # metres in the file
    doc.modelspace().add_line((0, 0), (1, 0))
    path = tmp_path / "units_override.dxf"
    doc.saveas(path)

    drawing = DxfParser().parse(str(path), units="mm")

    assert drawing.units == "mm"
    assert drawing._meta["units_source"] == "explicit_argument"

def test_dxf_parser_defaults_to_mm_when_insunits_is_unitless(tmp_path):
    import ezdxf

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 0
    doc.modelspace().add_line((0, 0), (1000, 0))
    path = tmp_path / "units_default.dxf"
    doc.saveas(path)

    drawing = DxfParser().parse(str(path))

    assert drawing.units == "mm"
    assert drawing._meta["units_source"] == "default_mm"



def test_dxf_parse_linework_gap_detection_and_room_label_end_to_end(tmp_path):
    """Real DXF parsing, unit-aware gap snapping, and label association integrate."""
    import ezdxf
    from core.analyzer.room_detector import (
        associate_room_names,
        detect_linework_room_candidates,
    )

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4  # millimetres
    msp = doc.modelspace()
    # A 0.5 mm endpoint gap should be closed by the default 1 mm tolerance.
    msp.add_line((0, 0), (5000, 0), dxfattribs={"layer": "WALLS"})
    msp.add_line((5000.5, 0), (5000.5, 4000), dxfattribs={"layer": "WALLS"})
    msp.add_line((5000.5, 4000), (0, 4000), dxfattribs={"layer": "WALLS"})
    msp.add_line((0, 4000), (0, 0), dxfattribs={"layer": "WALLS"})
    msp.add_text(
        "会議室",
        dxfattribs={"insert": (2500, 2000), "height": 250, "layer": "ROOM_LABELS"},
    )
    path = tmp_path / "linework_gap_room.dxf"
    doc.saveas(path)

    drawing = DxfParser().parse(str(path))
    rooms = detect_linework_room_candidates(drawing)
    associated = associate_room_names(drawing, rooms)

    assert drawing.units == "mm"
    assert len(associated) == 1
    assert associated[0].area_m2 == pytest.approx(20.0, rel=0.001)
    assert associated[0].room_name == "会議室"
    assert associated[0].properties["candidate_type"] == "closed_linework"
    assert associated[0].properties["room_name_association"] == "single_text_inside_candidate"
