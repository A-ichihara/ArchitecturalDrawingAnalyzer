"""二重線の壁の検出と壁芯面積の算出テスト。"""
import os

import pytest

from core.analyzer.wall_detector import (
    attach_wall_info,
    detect_wall_pairs,
)
from core.models.drawing import Drawing, LineElement, PolylineElement
from core.models.room import Room


def _drawing(elements, units="mm"):
    return Drawing(
        drawing_id="wall-test",
        file_name="wall-test.dxf",
        file_type="dxf",
        units=units,
        elements=elements,
    )


def _line(element_id, start, end, layer="WALL"):
    return LineElement(
        element_id=element_id, element_type="LINE", layer=layer, start=list(start), end=list(end)
    )


def _rect_polyline(element_id, x1, y1, x2, y2, layer="ROOM"):
    return PolylineElement(
        element_id=element_id,
        element_type="LWPOLYLINE",
        layer=layer,
        points=[[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
        is_closed=True,
    )


def test_parallel_lines_form_one_wall_pair():
    drawing = _drawing(
        [
            _line("L1", (0, 0), (5000, 0)),
            _line("L2", (0, 200), (5000, 200)),
        ]
    )
    pairs = detect_wall_pairs(drawing)
    assert len(pairs) == 1
    assert pairs[0].thickness == pytest.approx(200.0)
    # 壁芯は2本の線の中間（y=100）で、重なり区間全体。
    assert pairs[0].centerline == [[0, 100.0], [5000, 100.0]]


def test_non_parallel_or_too_far_lines_are_not_walls():
    far = _drawing([_line("L1", (0, 0), (5000, 0)), _line("L2", (0, 1000), (5000, 1000))])
    assert detect_wall_pairs(far) == []
    diagonal = _drawing([_line("L1", (0, 0), (5000, 0)), _line("L2", (0, 200), (4000, 1200))])
    assert detect_wall_pairs(diagonal) == []


def test_short_overlap_is_not_a_wall():
    drawing = _drawing(
        [
            _line("L1", (0, 0), (5000, 0)),
            _line("L2", (4000, 200), (9000, 200)),  # 重なりは短い方の 20%
        ]
    )
    assert detect_wall_pairs(drawing) == []


def test_centerline_covers_only_the_overlap():
    drawing = _drawing(
        [
            _line("L1", (0, 0), (5000, 0)),
            _line("L2", (1000, 200), (4000, 200)),
        ]
    )
    pairs = detect_wall_pairs(drawing)
    assert len(pairs) == 1
    assert pairs[0].centerline == [[1000, 100.0], [4000, 100.0]]


def test_room_with_double_walls_gets_centerline_area():
    # 内法 4000x3000 の部屋。外側 200mm の位置に壁の外面がある。
    elements = [
        _rect_polyline("ROOM1", 0, 0, 4000, 3000),
        _line("W1", (-200, -200), (4200, -200)),
        _line("W2", (-200, 3200), (4200, 3200)),
        _line("W3", (-200, -200), (-200, 3200)),
        _line("W4", (4200, -200), (4200, 3200)),
    ]
    drawing = _drawing(elements)
    pairs = detect_wall_pairs(drawing)
    assert len(pairs) == 4

    room = Room(
        room_id="ROOM_CANDIDATE_000001",
        room_name="",
        area_m2=12.0,
        boundary=[[0, 0], [4000, 0], [4000, 3000], [0, 3000]],
    )
    assert attach_wall_info([room], pairs, 1e-6) == 1
    assert room.wall_type == "inner"
    # 壁芯面積 = (4000+200) x (3000+200) = 13.44 m²
    assert room.properties["area_centerline_m2"] == pytest.approx(13.44)
    assert room.properties["wall_thicknesses_mm"] == [200.0, 200.0, 200.0, 200.0]


def test_room_with_partial_walls_has_no_centerline_area():
    elements = [
        _rect_polyline("ROOM1", 0, 0, 4000, 3000),
        _line("W1", (-200, -200), (4200, -200)),
        _line("W2", (-200, 3200), (4200, 3200)),
    ]
    drawing = _drawing(elements)
    pairs = detect_wall_pairs(drawing)
    room = Room(
        room_id="ROOM_CANDIDATE_000001",
        room_name="",
        area_m2=12.0,
        boundary=[[0, 0], [4000, 0], [4000, 3000], [0, 3000]],
    )
    assert attach_wall_info([room], pairs, 1e-6) == 0
    assert room.wall_type == "unknown"
    assert "area_centerline_m2" not in room.properties


def test_outer_face_loop_gets_no_centerline_area():
    # 壁の外面で囲まれたループは部屋ではない。反対側の面が
    # ループの内側にあるため、壁芯面積の対象外とする。
    elements = [
        _rect_polyline("ROOM1", 0, 0, 4000, 3000),
        _line("W1", (-200, -200), (4200, -200)),
        _line("W2", (-200, 3200), (4200, 3200)),
        _line("W3", (-200, -200), (-200, 3200)),
        _line("W4", (4200, -200), (4200, 3200)),
    ]
    drawing = _drawing(elements)
    pairs = detect_wall_pairs(drawing)
    assert len(pairs) == 4
    outer_loop = Room(
        room_id="ROOM_LINEWORK_000001",
        room_name="",
        area_m2=14.96,
        boundary=[[-200, -200], [4200, -200], [4200, 3200], [-200, 3200]],
    )
    assert attach_wall_info([outer_loop], pairs, 1e-6) == 0
    assert outer_loop.wall_type == "unknown"
    assert "area_centerline_m2" not in outer_loop.properties


def test_wall_detection_on_real_sample_does_not_crash():
    from core.parser.dxf_parser import DxfParser

    # sample_p2_complex.dxf は samples/ にある（data/ には無い）。
    samples_dir = os.path.join(os.path.dirname(__file__), "..", "samples")
    drawing = DxfParser().parse(os.path.join(samples_dir, "sample_p2_complex.dxf"))
    assert len(drawing.elements) > 100
    first = detect_wall_pairs(drawing)
    second = detect_wall_pairs(drawing)
    assert len(first) == len(second)
    assert len(first) > 0
    assert all(50.0 <= pair.thickness <= 500.0 for pair in first)


def test_tiny_cell_long_segments_do_not_explode_grid():
    # 5000 単位の線分に 0.5 単位のセル（mm の数値を m 単位と誤認した
    # 場合）では、グリッドへの登録数が約 10 万件に膨れ上がる。
    # 総当たりへの切り替えにより、候補は同じ 4 組を瞬時に返す。
    from core.analyzer.wall_detector import _candidate_pairs, _Segment

    segments = [
        _Segment((0.0, 0.0), (5000.0, 0.0)),
        _Segment((5000.0, 0.0), (5000.0, 3000.0)),
        _Segment((5000.0, 3000.0), (0.0, 3000.0)),
        _Segment((0.0, 3000.0), (0.0, 0.0)),
    ]
    assert _candidate_pairs(segments, 0.5) == [(0, 1), (0, 3), (1, 2), (2, 3)]
    assert _candidate_pairs(segments, 500.0) == [(0, 1), (0, 3), (1, 2), (2, 3)]


def test_wall_detection_with_metre_units_on_mm_numbers():
    # test_changing_units_recalculates_areas と同じ状況：5000x3000 の
    # 数値を m 単位と誤認した場合。壁ペアは 0 件で、グリッドの爆発で
    # 落ちないこと。
    drawing = _drawing([_rect_polyline("ROOM1", 0, 0, 5000, 3000)], units="m")
    assert detect_wall_pairs(drawing) == []


def test_candidate_pairs_never_miss_close_pairs():
    # グリッド経路・総当たり経路のどちらでも、距離が最大距離以内の
    # 組は必ず候補に含まれる（絞り込みの漏れがないこと）。
    from shapely.geometry import LineString

    from core.analyzer.wall_detector import _candidate_pairs, _Segment

    segments = [
        _Segment((0.0, 0.0), (5000.0, 0.0)),
        _Segment((0.0, 200.0), (5000.0, 200.0)),
        _Segment((0.0, 1000.0), (5000.0, 1000.0)),
        _Segment((100.0, 0.0), (100.0, 3000.0)),
        _Segment((4000.0, 0.0), (4000.0, 3000.0)),
    ]
    for max_distance in (500.0, 0.5, 200.0):
        result = _candidate_pairs(segments, max_distance)
        assert result == sorted(set(result))
        for i in range(len(segments)):
            for j in range(i + 1, len(segments)):
                a = LineString([segments[i].p1, segments[i].p2])
                b = LineString([segments[j].p1, segments[j].p2])
                if float(a.distance(b)) <= max_distance:
                    assert (i, j) in result


def test_large_n_tiny_cell_uses_strtree_fallback():
    # 線分が多く（総当たりできない）、かつセルが線分に比べて極端に
    # 小さい場合、STRtree で最大距離以内の組を直接求める。グリッド
    # だけでは登録数が爆発し、セル拡大ではセル内の組の列挙が爆発する。
    from core.analyzer.wall_detector import _candidate_pairs, _Segment

    segments = [
        _Segment((float(i * 10), 0.0), (float(i * 10), 5000.0)) for i in range(600)
    ]
    segments.append(_Segment((0.4, 0.0), (0.4, 5000.0)))
    # 0.5 以内にあるのは x=0 と x=0.4 の線だけ。
    assert _candidate_pairs(segments, 0.5) == [(0, 600)]
