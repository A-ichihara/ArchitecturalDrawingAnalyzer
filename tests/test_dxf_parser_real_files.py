import math

import ezdxf

from core.models.drawing import (
    ArcElement,
    CircleElement,
    LineElement,
    PolylineElement,
    TextElement,
)
from core.parser.dxf_parser import DxfParser


def test_parse_real_dxf_entities(tmp_path):
    """Parse supported entities from an actual temporary DXF file."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    msp.add_line((0, 0), (3000, 4000), dxfattribs={"layer": "WALL"})
    msp.add_lwpolyline(
        [(0, 0, 1.0), (10, 0, 0.0)],
        format="xyb",
        dxfattribs={"layer": "CURVE"},
    )
    msp.add_arc((100, 100), radius=25, start_angle=0, end_angle=90)
    msp.add_circle((200, 200), radius=30)
    msp.add_text(
        "会議室",
        dxfattribs={"insert": (500, 600), "height": 250, "layer": "ROOM_NAME"},
    )
    msp.add_mtext(
        "機械室",
        dxfattribs={"insert": (700, 800), "char_height": 200, "layer": "ROOM_NAME"},
    )

    file_path = tmp_path / "sample_plan.dxf"
    doc.saveas(file_path)

    drawing = DxfParser().parse(str(file_path), scale=100, units="mm")

    assert drawing.drawing_id == "sample_plan"
    assert drawing.file_name == "sample_plan.dxf"
    assert drawing.file_type == "dxf"
    assert drawing.scale == 100
    assert drawing.units == "mm"
    assert len(drawing.elements) == 6

    line = next(e for e in drawing.elements if isinstance(e, LineElement))
    assert line.layer == "WALL"
    assert line.start == [0.0, 0.0]
    assert line.end == [3000.0, 4000.0]
    assert line.length == 5000.0

    polyline = next(e for e in drawing.elements if isinstance(e, PolylineElement))
    assert polyline.layer == "CURVE"
    assert polyline.points == [[0.0, 0.0], [10.0, 0.0]]
    assert polyline.bulge_list == [1.0, 0.0]
    assert math.isclose(polyline.length, 5 * math.pi)

    arc = next(e for e in drawing.elements if isinstance(e, ArcElement))
    assert arc.center == [100.0, 100.0]
    assert arc.radius == 25.0
    assert arc.start_angle == 0.0
    assert arc.end_angle == 90.0

    circle = next(e for e in drawing.elements if isinstance(e, CircleElement))
    assert circle.center == [200.0, 200.0]
    assert circle.radius == 30.0

    texts = [e for e in drawing.elements if isinstance(e, TextElement)]
    assert {e.text for e in texts} == {"会議室", "機械室"}
    assert {e.element_type for e in texts} == {"TEXT", "MTEXT"}


def test_parse_infers_supported_units_from_dxf_insunits(tmp_path):
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6  # metres
    doc.modelspace().add_lwpolyline(
        [(0, 0), (5, 0), (5, 4), (0, 4)],
        close=True,
    )
    path = tmp_path / "metres.dxf"
    doc.saveas(path)

    drawing = DxfParser().parse(str(path))

    assert drawing.units == "m"
    assert drawing._meta["dxf_insunits"] == 6
    assert drawing._meta["units_source"] == "dxf_insunits"


def test_parse_maps_all_supported_dxf_insunits_values(tmp_path):
    expected = {1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m"}
    for insunits, expected_unit in expected.items():
        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = insunits
        path = tmp_path / f"unit_{insunits}.dxf"
        doc.saveas(path)

        drawing = DxfParser().parse(str(path))

        assert drawing.units == expected_unit
        assert drawing._meta["dxf_insunits"] == insunits
        assert drawing._meta["units_source"] == "dxf_insunits"


def test_parse_explicit_units_override_dxf_insunits(tmp_path):
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6
    path = tmp_path / "override.dxf"
    doc.saveas(path)

    drawing = DxfParser().parse(str(path), units="mm")

    assert drawing.units == "mm"
    assert drawing._meta["units_source"] == "explicit_argument"


def test_parse_unitless_dxf_preserves_millimetre_fallback(tmp_path):
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 0
    path = tmp_path / "unitless.dxf"
    doc.saveas(path)

    drawing = DxfParser().parse(str(path))

    assert drawing.units == "mm"
    assert drawing._meta["units_source"] == "default_mm"


def test_get_layer_info_from_real_dxf(tmp_path):
    doc = ezdxf.new("R2010")
    doc.layers.new("WALL", dxfattribs={"color": 1})
    doc.layers.new("ROOM_NAME", dxfattribs={"color": 3})
    doc.layers.get("ROOM_NAME").off()

    file_path = tmp_path / "layers.dxf"
    doc.saveas(file_path)

    layers = DxfParser().get_layer_info(str(file_path))
    by_name = {layer["name"]: layer for layer in layers}

    assert by_name["WALL"]["color"] == 1
    assert by_name["WALL"]["is_on"] is True
    assert by_name["ROOM_NAME"]["color"] == 3
    assert by_name["ROOM_NAME"]["is_on"] is False


def test_parse_preserves_initial_layer_visibility(tmp_path):
    doc = ezdxf.new("R2010")
    doc.layers.new("VISIBLE", dxfattribs={"color": 2})
    doc.layers.new("HIDDEN", dxfattribs={"color": 5})
    doc.layers.get("HIDDEN").off()
    doc.modelspace().add_line((0, 0), (1, 1), dxfattribs={"layer": "HIDDEN"})
    path = tmp_path / "hidden.dxf"
    doc.saveas(path)

    drawing = DxfParser().parse(str(path))
    assert drawing._meta["layers"]["VISIBLE"] == {"color": 2, "is_on": True}
    assert drawing._meta["layers"]["HIDDEN"] == {"color": 5, "is_on": False}
    assert drawing.elements[0].layer == "HIDDEN"


def test_parse_invalid_dxf_reports_read_error(tmp_path):
    path = tmp_path / "broken.dxf"
    path.write_text("this is not a DXF file", encoding="utf-8")

    drawing = DxfParser().parse(str(path))

    assert drawing.elements == []
    assert "load_error" in drawing._meta
    assert drawing._meta["load_error"]


def test_parse_counts_failed_entity_conversions(tmp_path, monkeypatch):
    """Conversion errors should be distinguishable from unsupported DXF types."""
    doc = ezdxf.new("R2010")
    doc.modelspace().add_line((0, 0), (1, 1))
    path = tmp_path / "failed_entity.dxf"
    doc.saveas(path)

    def fail_conversion(entity, index):
        raise ValueError("malformed entity")

    monkeypatch.setattr(DxfParser, "_convert_entity", fail_conversion)
    drawing = DxfParser().parse(str(path))

    assert drawing.elements == []
    assert drawing._meta["failed_types"] == {"LINE": 1}
    assert drawing._meta["unsupported_types"] == {}
    assert "load_error" not in drawing._meta
