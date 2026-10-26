"""
tests/test_dxf_parser.py
DxfParser の実装テスト。テスト用DXFファイルを使って動作確認を行う。
"""

import os
import ezdxf
import pytest
from core.analyzer.room_detector import detect_closed_polyline_room_candidates
from core.parser.dxf_parser import DxfParser
from core.models.drawing import Drawing, LineElement, PolylineElement, TextElement

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "samples")


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


def test_sample_01_rect_area_is_15_m2():
    """sample_01（5000x3000）は 15 m² になること。単位宣言の誤りで100万倍にならない。"""
    filepath = _data_path("sample_01_rect.dxf")
    if not os.path.exists(filepath):
        pytest.skip(f"テストファイルが存在しません: {filepath}")
    drawing = DxfParser().parse(filepath)
    assert drawing.units == "mm"
    assert drawing._meta.get("units_warning") is None  # type: ignore[attr-defined]
    rooms = detect_closed_polyline_room_candidates(drawing)
    assert len(rooms) == 1
    assert rooms[0].area_m2 == pytest.approx(15.0)


def test_sample_02_multi_rect_areas_are_12_m2_each():
    """sample_02（隣接2矩形）は各 12 m² になること。"""
    filepath = _data_path("sample_02_multi_rect.dxf")
    if not os.path.exists(filepath):
        pytest.skip(f"テストファイルが存在しません: {filepath}")
    drawing = DxfParser().parse(filepath)
    assert drawing.units == "mm"
    rooms = detect_closed_polyline_room_candidates(drawing)
    assert len(rooms) == 2
    assert sorted(room.area_m2 for room in rooms) == pytest.approx([12.0, 12.0])


def test_sample_p2_complex_areas_are_realistic():
    """sample_p2_complex の部屋候補面積はすべて現実的な範囲に収まること。"""
    filepath = os.path.join(SAMPLES_DIR, "sample_p2_complex.dxf")
    if not os.path.exists(filepath):
        pytest.skip(f"テストファイルが存在しません: {filepath}")
    drawing = DxfParser().parse(filepath)
    assert drawing.units == "mm"
    assert drawing._meta.get("units_warning") is None  # type: ignore[attr-defined]
    rooms = detect_closed_polyline_room_candidates(drawing)
    assert rooms, "部屋候補が1件も検出されない"
    assert max(room.area_m2 for room in rooms) < 10_000.0


def _write_rect_dxf(path, insunits, width, height):
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = insunits
    msp = doc.modelspace()
    poly = msp.add_lwpolyline([(0, 0), (width, 0), (width, height), (0, height)])
    poly.close(True)
    doc.saveas(path)


def test_parser_warns_when_metre_declaration_conflicts_with_mm_scale_coordinates(tmp_path):
    """mm桁の座標にメートル宣言が付いた図面では、単位の警告が出ること。"""
    filepath = tmp_path / "mm_coords_metre_unit.dxf"
    _write_rect_dxf(filepath, insunits=6, width=5000, height=3000)
    drawing = DxfParser().parse(str(filepath))
    assert drawing.units == "m"
    warning = drawing._meta.get("units_warning")  # type: ignore[attr-defined]
    assert warning is not None
    assert "単位設定を確認してください" in warning


def test_parser_does_not_warn_for_metre_scale_coordinates(tmp_path):
    """メートル桁の座標にメートル宣言が付いた図面では、警告が出ないこと。"""
    filepath = tmp_path / "metre_coords.dxf"
    _write_rect_dxf(filepath, insunits=6, width=5, height=3)
    drawing = DxfParser().parse(str(filepath))
    assert drawing.units == "m"
    assert drawing._meta.get("units_warning") is None  # type: ignore[attr-defined]


def test_parser_does_not_warn_for_mm_declared_coordinates(tmp_path):
    """mm宣言の図面では、座標が大きくても警告が出ないこと。"""
    filepath = tmp_path / "mm_coords.dxf"
    _write_rect_dxf(filepath, insunits=4, width=5000, height=3000)
    drawing = DxfParser().parse(str(filepath))
    assert drawing.units == "mm"
    assert drawing._meta.get("units_warning") is None  # type: ignore[attr-defined]


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


def test_dxf_parse_adjacent_linework_rooms_keep_distinct_labels(tmp_path):
    """Adjacent rooms remain separate and each receives only its own label."""
    import ezdxf
    from core.analyzer.room_detector import (
        associate_room_names,
        detect_linework_room_candidates,
    )

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4  # millimetres
    msp = doc.modelspace()
    # Two 5 m x 4 m rooms share a wall at x=5000 mm.
    for start, end in [
        ((0, 0), (10000, 0)),
        ((10000, 0), (10000, 4000)),
        ((10000, 4000), (0, 4000)),
        ((0, 4000), (0, 0)),
        ((5000, 0), (5000, 4000)),
    ]:
        msp.add_line(start, end, dxfattribs={"layer": "WALLS"})
    msp.add_text(
        "事務室",
        dxfattribs={"insert": (2500, 2000), "height": 250, "layer": "ROOM_LABELS"},
    )
    msp.add_text(
        "会議室",
        dxfattribs={"insert": (7500, 2000), "height": 250, "layer": "ROOM_LABELS"},
    )
    path = tmp_path / "adjacent_rooms.dxf"
    doc.saveas(path)

    drawing = DxfParser().parse(str(path))
    rooms = detect_linework_room_candidates(drawing)
    associated = associate_room_names(drawing, rooms)

    assert drawing.units == "mm"
    assert len(associated) == 2
    assert sorted(room.area_m2 for room in associated) == pytest.approx([20.0, 20.0])
    assert {room.room_name for room in associated} == {"事務室", "会議室"}

@pytest.mark.parametrize("insunits", [3, 7, 8, 20, 99])
def test_dxf_parser_defaults_to_mm_for_unsupported_insunits(tmp_path, insunits):
    """Unknown DXF unit codes must use the documented legacy mm fallback."""
    import ezdxf

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = insunits
    doc.modelspace().add_line((0, 0), (1000, 0))
    path = tmp_path / f"unsupported_units_{insunits}.dxf"
    doc.saveas(path)

    drawing = DxfParser().parse(str(path))

    assert len(drawing.elements) == 1
    assert drawing.units == "mm"
    assert drawing._meta["units_source"] == "default_mm"

def test_dxf_parser_preserves_insert_block_transform_metadata(tmp_path):
    """Block references retain their transform instead of being silently flattened."""
    import ezdxf
    from core.models.drawing import InsertElement

    doc = ezdxf.new("R2010")
    block = doc.blocks.new(name="DOOR_SYMBOL")
    block.add_line((0, 0), (900, 0))
    doc.modelspace().add_blockref(
        "DOOR_SYMBOL",
        insert=(1000, 2000),
        dxfattribs={
            "rotation": 30,
            "xscale": 2,
            "yscale": 3,
            "zscale": 1,
            "layer": "DOORS",
        },
    )
    path = tmp_path / "insert_transform.dxf"
    doc.saveas(path)

    drawing = DxfParser().parse(str(path))

    inserts = [element for element in drawing.elements if isinstance(element, InsertElement)]
    assert len(inserts) == 1
    insert = inserts[0]
    assert insert.block_name == "DOOR_SYMBOL"
    assert insert.insert_point == pytest.approx([1000, 2000])
    assert insert.rotation == pytest.approx(30)
    assert insert.scale_x == pytest.approx(2)
    assert insert.scale_y == pytest.approx(3)
    assert insert.scale_z == pytest.approx(1)
    assert insert.layer == "DOORS"

def test_dxf_parser_keeps_supported_geometry_when_hatch_is_unsupported(tmp_path):
    """Unsupported fill entities are reported without discarding supported lines."""
    import ezdxf
    from core.models.drawing import LineElement

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_line((0, 0), (5000, 0), dxfattribs={"layer": "WALLS"})
    hatch = msp.add_hatch(dxfattribs={"layer": "FILL"})
    hatch.paths.add_polyline_path(
        [(100, 100), (900, 100), (900, 900), (100, 900)],
        is_closed=True,
    )
    path = tmp_path / "supported_and_unsupported_entities.dxf"
    doc.saveas(path)

    drawing = DxfParser().parse(str(path))

    lines = [element for element in drawing.elements if isinstance(element, LineElement)]
    assert len(lines) == 1
    assert lines[0].start == pytest.approx([0, 0])
    assert lines[0].end == pytest.approx([5000, 0])
    assert drawing._meta["unsupported_types"].get("HATCH") == 1
    assert drawing._meta["failed_types"] == {}

def test_dxf_parser_keeps_later_entities_when_one_conversion_fails(tmp_path, monkeypatch):
    """A single malformed entity must not prevent later valid entities loading."""
    import ezdxf
    from core.models.drawing import LineElement

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0), dxfattribs={"layer": "BROKEN"})
    msp.add_line((200, 0), (300, 0), dxfattribs={"layer": "VALID"})
    path = tmp_path / "one_entity_conversion_failure.dxf"
    doc.saveas(path)

    parser = DxfParser()
    original_convert = parser._convert_entity

    def fail_first_line(entity, index):
        if entity.dxftype() == "LINE" and entity.dxf.layer == "BROKEN":
            raise ValueError("simulated malformed entity")
        return original_convert(entity, index)

    monkeypatch.setattr(parser, "_convert_entity", fail_first_line)
    drawing = parser.parse(str(path))

    lines = [element for element in drawing.elements if isinstance(element, LineElement)]
    assert len(lines) == 1
    assert lines[0].layer == "VALID"
    assert lines[0].start == pytest.approx([200, 0])
    assert drawing._meta["failed_types"] == {"LINE": 1}
    assert drawing._meta["unsupported_types"] == {}

def test_dxf_parser_rejects_partially_read_polyline_vertices():
    """A broken vertex iterator must not yield a truncated closed boundary."""
    from types import SimpleNamespace

    def broken_vertices():
        yield SimpleNamespace(
            dxf=SimpleNamespace(
                location=SimpleNamespace(x=0.0, y=0.0),
                get=lambda key, default: default,
            )
        )
        raise ValueError("vertex stream truncated")

    entity = SimpleNamespace(vertices=broken_vertices(), is_closed=True)

    with pytest.raises(ValueError, match="vertex stream truncated"):
        DxfParser()._convert_polyline(entity, "POLYLINE_000001", "WALLS", None)


def test_renderer_continues_after_unexpected_element_error(monkeypatch):
    """A failure for one element must not prevent later elements from rendering."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from core.drawing_viewer.renderers import DxfRenderer
    from core.drawing_viewer.scene import DrawingScene, DrawingLayer
    from core.models.drawing import Drawing, LineElement

    app = QApplication.instance() or QApplication([])
    drawing = Drawing(
        drawing_id="render-test",
        file_name="render-test.dxf",
        file_type="dxf",
        elements=[
            LineElement(element_id="bad", element_type="LINE", start=[0, 0], end=[1, 1]),
            LineElement(element_id="good", element_type="LINE", start=[1, 1], end=[2, 2]),
        ],
    )
    renderer = DxfRenderer()
    create_item = renderer._create_item

    def fail_first(element):
        if element.element_id == "bad":
            raise RuntimeError("simulated renderer failure")
        return create_item(element)

    monkeypatch.setattr(renderer, "_create_item", fail_first)
    scene = DrawingScene()
    renderer.render(drawing, scene)

    base_group = scene._layers[int(DrawingLayer.BASE)]
    assert len(base_group.childItems()) == 1
    assert base_group.childItems()[0].data(Qt.ItemDataRole.UserRole) == "good"
    assert app is not None


@pytest.mark.parametrize("invalid_color", [None, "not-an-integer", float("inf")])
def test_renderer_uses_default_color_for_invalid_aci_values(invalid_color):
    """Invalid DXF color metadata must not crash pen creation."""
    from core.drawing_viewer.renderers import DxfRenderer, DEFAULT_LINE_COLOR
    from core.models.drawing import LineElement

    element = LineElement(
        element_id="invalid-color",
        element_type="LINE",
        color=invalid_color,
        start=[0, 0],
        end=[1, 1],
    )

    pen = DxfRenderer()._get_pen(element)

    assert pen.color() == DEFAULT_LINE_COLOR
