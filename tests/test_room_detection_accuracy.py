"""合成テスト図面による検出精度の確認（完成基準 §8）。

矩形・凹凸・共有壁・二重壁・柱・開口部・寸法線・ハッチングを
含む合成図面で、部屋の検出・部屋名の関連付け・壁の検出が
期待どおりに動くことを確認する。実図面の代わりに、図面の
特徴ごとに期待値を定めた合成図面を使う。
"""
import os

import pytest

from core.analyzer.room_detector import (
    associate_room_names,
    deduplicate_room_candidates,
    detect_closed_polyline_room_candidates,
    detect_linework_room_candidates,
)
from core.analyzer.wall_detector import (
    area_factor_for_units,
    attach_wall_info,
    detect_wall_pairs,
)
from core.models.drawing import Drawing, LineElement, PolylineElement, TextElement
from core.models.room import Room


def _line(element_id, start, end, layer="WALL"):
    return LineElement(
        element_id=element_id, element_type="LINE", layer=layer,
        start=list(start), end=list(end),
    )


def _polyline(element_id, points, layer="ROOM"):
    return PolylineElement(
        element_id=element_id, element_type="LWPOLYLINE", layer=layer,
        points=[list(p) for p in points], is_closed=True,
    )


def _text(element_id, text, insert, layer="TEXT"):
    return TextElement(
        element_id=element_id, element_type="TEXT", layer=layer,
        text=text, insertion_point=list(insert), height=250.0,
    )


def _drawing(elements, units="mm"):
    return Drawing(
        drawing_id="accuracy-test", file_name="accuracy-test.dxf",
        file_type="dxf", units=units, elements=elements,
    )


def _detect_all(drawing):
    """ポリライン＋線分の両検出器を通し、重複除去と部屋名関連付けまで行う。"""
    rooms = deduplicate_room_candidates(
        detect_closed_polyline_room_candidates(drawing),
        detect_linework_room_candidates(drawing),
    )
    return associate_room_names(drawing, rooms)


def test_concave_l_shaped_room_area():
    # L字形の部屋：下部 5000x2000（10 m²）＋右上 2000x2000（4 m²）＝ 14 m²。
    points = [[0, 0], [5000, 0], [5000, 4000], [3000, 4000], [3000, 2000], [0, 2000]]
    rooms = _detect_all(_drawing([_polyline("L", points)]))
    assert len(rooms) == 1
    assert rooms[0].area_m2 == pytest.approx(14.0)


def test_two_rooms_sharing_a_wall_have_no_overlap():
    elements = [
        _line("BOTTOM", [0, 0], [10000, 0]),
        _line("TOP", [10000, 4000], [0, 4000]),
        _line("LEFT", [0, 4000], [0, 0]),
        _line("RIGHT", [10000, 0], [10000, 4000]),
        _line("PARTITION", [5000, 0], [5000, 4000]),
        _text("T1", "事務室", (2000, 2000)),
        _text("T2", "会議室", (7000, 2000)),
    ]
    rooms = _detect_all(_drawing(elements))
    assert len(rooms) == 2
    assert sorted(r.area_m2 for r in rooms) == pytest.approx([20.0, 20.0])
    assert sorted(r.room_name for r in rooms) == ["事務室", "会議室"]


def test_double_wall_room_gets_centerline_area():
    # 内法 4000x3000、壁厚 200mm の二重壁。壁芯面積は 13.44 m²。
    elements = [
        _polyline("ROOM", [[0, 0], [4000, 0], [4000, 3000], [0, 3000]]),
        _line("W1", (-200, -200), (4200, -200)),
        _line("W2", (-200, 3200), (4200, 3200)),
        _line("W3", (-200, -200), (-200, 3200)),
        _line("W4", (4200, -200), (4200, 3200)),
    ]
    drawing = _drawing(elements)
    rooms = _detect_all(drawing)
    inner = next(r for r in rooms if r.area_m2 == pytest.approx(12.0))
    pairs = detect_wall_pairs(drawing)
    assert len(pairs) == 4
    assert attach_wall_info(rooms, pairs, area_factor_for_units(drawing.units)) == 1
    assert inner.wall_type == "inner"
    assert inner.properties["area_centerline_m2"] == pytest.approx(13.44)


def test_room_with_column_keeps_outer_area():
    # 部屋の中に柱（600x600 の閉じたポリライン）がある。
    # 外側の部屋は正しい面積で検出される。柱は既定の最小面積
    # （1 m²）未満のため候補にならない。しきい値を下げれば候補になる。
    elements = [
        _polyline("ROOM", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _polyline("COLUMN", [[2000, 1500], [2600, 1500], [2600, 2100], [2000, 2100]]),
    ]
    drawing = _drawing(elements)
    rooms = _detect_all(drawing)
    assert len(rooms) == 1
    assert rooms[0].area_m2 == pytest.approx(20.0)
    small = detect_closed_polyline_room_candidates(drawing, min_area_m2=0.1)
    assert sorted(r.area_m2 for r in small) == pytest.approx([0.36, 20.0])


def test_doorway_gap_prevents_linework_room_but_not_polyline_room():
    # 壁に 900mm の開口（ドア）がある線分の組み立ては、閉領域に
    # ならない。一方、同じ輪郭を閉じたポリラインで描けば部屋になる。
    open_walls = [
        _line("BOTTOM", [0, 0], [5000, 0]),
        _line("RIGHT", [5000, 0], [5000, 4000]),
        _line("TOP", [5000, 4000], [0, 4000]),
        _line("LEFT1", [0, 4000], [0, 2500]),
        _line("LEFT2", [0, 1600], [0, 0]),  # 900mm の開口
    ]
    assert detect_linework_room_candidates(_drawing(open_walls)) == []
    closed = _drawing([_polyline("ROOM", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]])])
    assert len(detect_closed_polyline_room_candidates(closed)) == 1


def test_dimension_lines_and_text_do_not_create_spurious_rooms():
    # 寸法線（長い線＋目盛）と寸法値は、部屋候補を作らない。
    elements = [
        _polyline("ROOM", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _line("DIM", [-500, 4500], [5500, 4500], layer="DIM"),
        _line("TICK1", [0, 4400], [0, 4600], layer="DIM"),
        _line("TICK2", [5000, 4400], [5000, 4600], layer="DIM"),
        _text("DIMTEXT", "5000", (2250, 4700), layer="DIM"),
    ]
    rooms = _detect_all(_drawing(elements))
    assert len(rooms) == 1
    assert rooms[0].area_m2 == pytest.approx(20.0)


def test_hatching_lines_do_not_create_spurious_rooms():
    # ハッチングを模した短い平行線の集まりは、部屋候補を作らない。
    elements = [_polyline("ROOM", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]])]
    for i in range(10):
        x = 500 + i * 400
        elements.append(_line(f"HATCH{i}", (x, 500), (x + 200, 1500), layer="HATCH"))
    rooms = _detect_all(_drawing(elements))
    assert len(rooms) == 1
    assert rooms[0].area_m2 == pytest.approx(20.0)


def test_three_room_layout_with_names():
    elements = []
    rooms_spec = [
        ("事務室", 0, 0, 5000, 4000),
        ("会議室", 5000, 0, 8000, 4000),
        ("廊下", 8000, 0, 10000, 4000),
    ]
    for i, (name, x1, y1, x2, y2) in enumerate(rooms_spec):
        elements.append(_polyline(f"R{i}", [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]))
        elements.append(_text(f"T{i}", name, ((x1 + x2) / 2 - 500, 2000)))
    rooms = _detect_all(_drawing(elements))
    assert len(rooms) == 3
    by_name = {r.room_name: r.area_m2 for r in rooms}
    assert by_name == pytest.approx({"事務室": 20.0, "会議室": 12.0, "廊下": 8.0})


def test_real_sample_p2_detection_snapshot():
    """最も現実的なサンプルでの検出結果のスナップショット。

    検出方法の変更で結果が変わったら気づけるよう、件数と
    面積の分布を固定する。
    """
    from core.parser.dxf_parser import DxfParser

    samples_dir = os.path.join(os.path.dirname(__file__), "..", "samples")
    drawing = DxfParser().parse(os.path.join(samples_dir, "sample_p2_complex.dxf"))
    assert len(drawing.elements) > 100
    rooms = _detect_all(drawing)
    assert len(rooms) == 21
    areas = sorted(round(r.area_m2, 1) for r in rooms)
    assert areas.count(16.0) == 20
    assert areas.count(320.0) == 1
    pairs = detect_wall_pairs(drawing)
    assert len(pairs) > 0
    attached = attach_wall_info(rooms, pairs, area_factor_for_units(drawing.units))
    assert attached == 11
