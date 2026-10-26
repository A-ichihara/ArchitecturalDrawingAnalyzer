"""INSERT（ブロック参照）展開のテスト。

ブロック定義の内容が挿入位置・回転・倍率を適用されて図形要素に
変換されること、展開できない参照はマーカーとして残ることを確認する。
"""
import os

import pytest
import ezdxf

from core.parser.dxf_parser import DxfParser
from core.models.drawing import (
    ArcElement, CircleElement, InsertElement, LineElement,
    PolylineElement, TextElement,
)

SAMPLES_DIR = os.path.join(
    os.path.dirname(__file__), "..", "samples"
)


def _save(doc, tmp_path, name):
    path = tmp_path / name
    doc.saveas(path)
    return str(path)


def test_expands_simple_block_with_layer_inheritance(tmp_path):
    """ブロック内の線が座標そのままに展開され、レイヤー0は挿入元を継承する。"""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    block = doc.blocks.new(name="RECT")
    block.add_line((0, 0), (1000, 0))
    block.add_line((1000, 0), (1000, 500))
    block.add_line((1000, 500), (0, 500))
    block.add_line((0, 500), (0, 0))
    # ブロック側で明示されたレイヤーは挿入元のレイヤーに置き換わらない。
    block.add_line((0, 0), (1000, 500), dxfattribs={"layer": "WALLS"})
    doc.modelspace().add_blockref("RECT", insert=(100, 200), dxfattribs={"layer": "DOORS"})

    drawing = DxfParser().parse(_save(doc, tmp_path, "block_rect.dxf"))

    assert not any(isinstance(e, InsertElement) for e in drawing.elements)
    lines = [e for e in drawing.elements if isinstance(e, LineElement)]
    assert len(lines) == 5
    assert lines[0].start == pytest.approx([100, 200])
    assert lines[0].end == pytest.approx([1100, 200])
    assert lines[0].layer == "DOORS"
    assert lines[0].properties["block_name"] == "RECT"
    assert lines[0].properties["source_insert_id"] == "INSERT_000000"
    assert lines[0].element_id == "INSERT_000000__001"
    assert lines[4].layer == "WALLS"
    assert drawing._meta["expanded_inserts"] == 1
    assert drawing._meta["insert_markers"] == 0


def test_expands_insert_with_rotation_and_scale(tmp_path):
    """90度回転・2倍の挿入で、ブロック内座標が正しく変換される。"""
    doc = ezdxf.new("R2010")
    block = doc.blocks.new(name="BAR")
    block.add_line((0, 0), (100, 0))
    doc.modelspace().add_blockref(
        "BAR",
        insert=(10, 20),
        dxfattribs={"rotation": 90, "xscale": 2, "yscale": 2},
    )

    drawing = DxfParser().parse(_save(doc, tmp_path, "block_rot.dxf"))

    lines = [e for e in drawing.elements if isinstance(e, LineElement)]
    assert len(lines) == 1
    assert lines[0].start == pytest.approx([10, 20])
    assert lines[0].end == pytest.approx([10, 220])


def test_expands_nested_blocks(tmp_path):
    """ブロック内のブロック参照も再帰的に展開される。"""
    doc = ezdxf.new("R2010")
    inner = doc.blocks.new(name="INNER")
    inner.add_line((0, 0), (100, 0))
    outer = doc.blocks.new(name="OUTER")
    outer.add_blockref("INNER", insert=(50, 0), dxfattribs={"rotation": 90})
    doc.modelspace().add_blockref(
        "OUTER", insert=(1000, 1000), dxfattribs={"xscale": 2, "yscale": 2}
    )

    drawing = DxfParser().parse(_save(doc, tmp_path, "block_nested.dxf"))

    lines = [e for e in drawing.elements if isinstance(e, LineElement)]
    assert len(lines) == 1
    # 内側の線 (0,0)-(100,0) は INNER 内で 90 度回転して (50,0)-(50,100) となり、
    # OUTER の 2 倍・(1000,1000) 平行移動で (1100,1000)-(1100,1200) になる。
    assert lines[0].start == pytest.approx([1100, 1000])
    assert lines[0].end == pytest.approx([1100, 1200])
    assert lines[0].properties["block_name"] == "INNER"


def test_cyclic_block_reference_terminates(tmp_path):
    """自己参照ブロックでも無限ループせず、マーカーとして残る。"""
    doc = ezdxf.new("R2010")
    block = doc.blocks.new(name="SELF")
    block.add_blockref("SELF", insert=(0, 0))
    doc.modelspace().add_blockref("SELF", insert=(0, 0))

    drawing = DxfParser().parse(_save(doc, tmp_path, "block_cyclic.dxf"))

    assert len(drawing.elements) == 1
    assert isinstance(drawing.elements[0], InsertElement)
    assert drawing._meta["expanded_inserts"] == 0
    assert drawing._meta["insert_markers"] == 1


def test_non_uniform_scale_skips_circle_but_keeps_lines(tmp_path):
    """非均一倍率では円（楕円になるため）を落とし、線は展開する。"""
    doc = ezdxf.new("R2010")
    block = doc.blocks.new(name="MIXED")
    block.add_circle((0, 0), radius=100)
    block.add_line((0, 0), (200, 0))
    doc.modelspace().add_blockref(
        "MIXED", insert=(0, 0), dxfattribs={"xscale": 2, "yscale": 3}
    )

    drawing = DxfParser().parse(_save(doc, tmp_path, "block_mixed.dxf"))

    assert not any(isinstance(e, CircleElement) for e in drawing.elements)
    lines = [e for e in drawing.elements if isinstance(e, LineElement)]
    assert len(lines) == 1
    assert lines[0].end == pytest.approx([400, 0])


def test_block_text_is_transformed(tmp_path):
    """ブロック内の文字は挿入点・高さ・回転が変換される。"""
    doc = ezdxf.new("R2010")
    block = doc.blocks.new(name="LABEL")
    block.add_text("会議室", dxfattribs={"insert": (100, 200), "height": 250})
    doc.modelspace().add_blockref(
        "LABEL",
        insert=(1000, 0),
        dxfattribs={"rotation": 90, "xscale": 2, "yscale": 2},
    )

    drawing = DxfParser().parse(_save(doc, tmp_path, "block_text.dxf"))

    texts = [e for e in drawing.elements if isinstance(e, TextElement)]
    assert len(texts) == 1
    assert texts[0].text == "会議室"
    assert texts[0].insertion_point == pytest.approx([600, 200])
    assert texts[0].height == pytest.approx(500)
    assert texts[0].rotation == pytest.approx(90)


def test_block_arc_is_transformed_with_uniform_scale(tmp_path):
    """均一倍率の弧は中心・半径・角度が変換される。"""
    doc = ezdxf.new("R2010")
    block = doc.blocks.new(name="DOOR_ARC")
    block.add_arc((0, 0), radius=100, start_angle=0, end_angle=90)
    doc.modelspace().add_blockref(
        "DOOR_ARC",
        insert=(100, 100),
        dxfattribs={"rotation": 90, "xscale": 2, "yscale": 2},
    )

    drawing = DxfParser().parse(_save(doc, tmp_path, "block_arc.dxf"))

    arcs = [e for e in drawing.elements if isinstance(e, ArcElement)]
    assert len(arcs) == 1
    assert arcs[0].center == pytest.approx([100, 100])
    assert arcs[0].radius == pytest.approx(200)
    assert arcs[0].start_angle == pytest.approx(90)
    assert arcs[0].end_angle == pytest.approx(180)


def test_room_inside_block_is_detectable(tmp_path):
    """ブロック内の閉じたポリラインから部屋候補が検出される。"""
    from core.analyzer.room_detector import detect_closed_polyline_room_candidates

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    block = doc.blocks.new(name="ROOM_A")
    block.add_lwpolyline(
        [(0, 0), (5000, 0), (5000, 4000), (0, 4000)],
        close=True,
    )
    doc.modelspace().add_blockref("ROOM_A", insert=(1000, 1000))

    drawing = DxfParser().parse(_save(doc, tmp_path, "block_room.dxf"))
    rooms = detect_closed_polyline_room_candidates(drawing)

    assert len(rooms) == 1
    assert rooms[0].area_m2 == pytest.approx(20.0, rel=0.001)
    # The room boundary is the block polyline, shifted by the insert point.
    assert rooms[0].boundary == [
        [1000.0, 1000.0], [6000.0, 1000.0], [6000.0, 5000.0], [1000.0, 5000.0]
    ]
    assert rooms[0].properties["source_element_id"] == "INSERT_000000__001"


def test_sample_p2_complex_inserts_all_expand():
    """sample_p2_complex の INSERT 45 件がすべて展開され、マーカーが残らない。"""
    filepath = os.path.join(SAMPLES_DIR, "sample_p2_complex.dxf")
    drawing = DxfParser().parse(filepath)

    assert drawing._meta["expanded_inserts"] == 45
    assert drawing._meta["insert_markers"] == 0
    assert not any(isinstance(e, InsertElement) for e in drawing.elements)
    # 45 件のマーカーが、COLUMN（閉ポリライン 30 件）と DOOR（線＋弧 30 件）に置き換わる。
    assert len(drawing.elements) == 889
