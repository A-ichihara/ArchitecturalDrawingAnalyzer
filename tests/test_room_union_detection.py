"""壁ペア線分の部屋検出と全線分検出の統合、部屋名の近接関連付けの確認。

実図面 (寮の平面図) での検証から分かったこと:
- 全線分だけでは、共用部 (収納庫・待合・風除室) など壁面に沿った部屋が
  見つからない。一方、壁ペア線分だけでは単線の壁の部屋が見つからない。
- 両方を統合し、重なる部屋は壁ペア版を優先すると、部屋数と部屋名が増える
  (実図面: 95件→116件、名前21件→約29件)。
- 部屋名の文字が境界のすぐ外 (100mm以内) にある場合も拾う。
"""
import pytest

from core.analyzer.room_detector import (
    associate_room_names,
    deduplicate_room_candidates,
    detect_closed_polyline_room_candidates,
    detect_linework_room_candidates,
    detect_wall_pair_room_candidates,
    merge_room_candidates,
)
from core.analyzer.wall_detector import detect_wall_pairs
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
        drawing_id="union-test", file_name="union-test.dxf",
        file_type="dxf", units=units, elements=elements,
    )


def _room(room_id, boundary, area_m2=10.0, candidate_type="closed_linework"):
    return Room(
        room_id=room_id, room_name="", area_m2=area_m2,
        boundary=[list(p) for p in boundary],
        wall_type="unknown", confidence=0.4,
        properties={"candidate_type": candidate_type},
    )


def _double_wall_room(prefix, x0, y0, x1, y1, gap=150):
    """二重壁の部屋。各辺が gap だけ離れた2本の平行線で描かれている。"""
    return [
        _line(f"{prefix}B0", [x0, y0], [x1, y0]),
        _line(f"{prefix}B1", [x0, y0 + gap], [x1, y0 + gap]),
        _line(f"{prefix}T0", [x0, y1 - gap], [x1, y1 - gap]),
        _line(f"{prefix}T1", [x0, y1], [x1, y1]),
        _line(f"{prefix}L0", [x0, y0], [x0, y1]),
        _line(f"{prefix}L1", [x0 + gap, y0], [x0 + gap, y1]),
        _line(f"{prefix}R0", [x1 - gap, y0], [x1 - gap, y1]),
        _line(f"{prefix}R1", [x1, y0], [x1, y1]),
    ]


def _single_line_room(prefix, x0, y0, x1, y1):
    """単線の壁の部屋。壁ペアにはならない。"""
    return [
        _line(f"{prefix}B", [x0, y0], [x1, y0]),
        _line(f"{prefix}T", [x0, y1], [x1, y1]),
        _line(f"{prefix}L", [x0, y0], [x0, y1]),
        _line(f"{prefix}R", [x1, y0], [x1, y1]),
    ]


def _detect_union(drawing):
    """全線分検出と壁ペア検出を統合し、部屋名まで関連付ける。"""
    wall_pairs = detect_wall_pairs(drawing)
    rooms = deduplicate_room_candidates(
        detect_closed_polyline_room_candidates(drawing),
        detect_linework_room_candidates(drawing),
    )
    wall_rooms = detect_wall_pair_room_candidates(drawing, wall_pairs)
    rooms = merge_room_candidates(rooms, wall_rooms)
    return associate_room_names(drawing, rooms)


def test_wall_pair_detection_finds_double_wall_room():
    elements = _double_wall_room("A", 0, 0, 4000, 3000)
    drawing = _drawing(elements)
    rooms = detect_wall_pair_room_candidates(drawing)
    assert len(rooms) == 1
    # 内側の面 (3700x2700) が部屋になる。壁の帯 (0.6m2) は最小面積未満で落ちる。
    assert rooms[0].area_m2 == pytest.approx(9.99)
    assert rooms[0].room_id.startswith("ROOM_WALLPAIR_")
    assert rooms[0].properties["candidate_type"] == "wall_pair_linework"


def test_wall_pair_detection_ignores_single_line_room():
    elements = _single_line_room("A", 0, 0, 3000, 3000)
    drawing = _drawing(elements)
    assert detect_wall_pair_room_candidates(drawing) == []
    # 全線分では見つかる。統合しないとこの部屋は失われる。
    assert len(detect_linework_room_candidates(drawing)) == 1


def test_merge_prefers_wall_pair_version_on_overlap():
    all_lines = [_room("ROOM_LINEWORK_000001", [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], 12.0)]
    wall_pair = [_room("ROOM_WALLPAIR_000001", [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], 12.0,
                       candidate_type="wall_pair_linework")]
    merged = merge_room_candidates(all_lines, wall_pair)
    assert len(merged) == 1
    assert merged[0].room_id == "ROOM_WALLPAIR_000001"


def test_merge_keeps_non_overlapping_rooms():
    all_lines = [_room("ROOM_LINEWORK_000001", [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], 12.0)]
    wall_pair = [_room("ROOM_WALLPAIR_000001", [[6000, 0], [10000, 0], [10000, 3000], [6000, 3000]], 12.0,
                       candidate_type="wall_pair_linework")]
    merged = merge_room_candidates(all_lines, wall_pair)
    assert len(merged) == 2
    assert {r.room_id for r in merged} == {"ROOM_LINEWORK_000001", "ROOM_WALLPAIR_000001"}


def test_merge_drops_invalid_boundary():
    all_lines = [_room("ROOM_LINEWORK_000001", [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], 12.0)]
    broken = [_room("ROOM_WALLPAIR_000001", [[0, 0], [0, 0]], 0.0,
                    candidate_type="wall_pair_linework")]
    merged = merge_room_candidates(all_lines, broken)
    assert len(merged) == 1
    assert merged[0].room_id == "ROOM_LINEWORK_000001"


def test_union_end_to_end_keeps_both_room_kinds():
    elements = _double_wall_room("A", 0, 0, 4000, 3000)
    elements += _single_line_room("B", 6000, 0, 9000, 3000)
    drawing = _drawing(elements)
    rooms = _detect_union(drawing)
    assert len(rooms) == 2
    assert {r.room_id.split("_")[1] for r in rooms} == {"LINEWORK", "WALLPAIR"}
    areas = sorted(r.area_m2 for r in rooms)
    assert areas == pytest.approx([9.0, 9.99])


def test_associate_near_text_within_tolerance():
    elements = _single_line_room("A", 0, 0, 4000, 3000)
    elements.append(_text("T1", "会議室", (4050, 1500)))  # 右壁の 50mm 外
    drawing = _drawing(elements)
    rooms = associate_room_names(
        drawing, detect_linework_room_candidates(drawing)
    )
    assert len(rooms) == 1
    assert rooms[0].room_name == "会議室"
    assert rooms[0].properties["room_name_association"] == "text_near_candidate"


def test_associate_near_text_beyond_tolerance_is_ignored():
    elements = _single_line_room("A", 0, 0, 4000, 3000)
    elements.append(_text("T1", "会議室", (4500, 1500)))  # 右壁の 500mm 外
    drawing = _drawing(elements)
    rooms = associate_room_names(
        drawing, detect_linework_room_candidates(drawing)
    )
    assert rooms[0].room_name == ""


def test_associate_near_text_ambiguous_between_two_rooms():
    elements = _single_line_room("A", 0, 0, 4000, 3000)
    elements += _single_line_room("B", 4200, 0, 8200, 3000)
    # 両部屋の壁から 100mm の位置。どちらの部屋か決められない。
    elements.append(_text("T1", "会議室", (4100, 1500)))
    drawing = _drawing(elements)
    rooms = associate_room_names(
        drawing, detect_linework_room_candidates(drawing)
    )
    assert all(r.room_name == "" for r in rooms)


def test_associate_exact_text_wins_over_near_text():
    elements = _single_line_room("A", 0, 0, 4000, 3000)
    elements.append(_text("T1", "会議室", (2000, 1500)))  # 部屋の内側
    elements.append(_text("T2", "倉庫", (4050, 1500)))  # 右壁の 50mm 外
    drawing = _drawing(elements)
    rooms = associate_room_names(
        drawing, detect_linework_room_candidates(drawing)
    )
    assert len(rooms) == 1
    assert rooms[0].room_name == "会議室"
    assert rooms[0].properties["room_name_association"] == "single_text_inside_candidate"


def test_room_detection_worker_emits_wall_pair_rooms_and_pairs():
    """検出ワーカーが壁ペア部屋と壁ペアも一緒に返す (MainWindow の配線確認)。"""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from ui.main_window import RoomDetectionWorker

    QApplication.instance() or QApplication([])
    elements = _double_wall_room("A", 0, 0, 4000, 3000)
    elements += _single_line_room("B", 6000, 0, 9000, 3000)
    drawing = _drawing(elements)
    worker = RoomDetectionWorker(drawing)
    received = {}

    def _on_finished(polyline_rooms, linework_rooms, wall_pair_rooms, wall_pairs):
        received["polyline"] = polyline_rooms
        received["linework"] = linework_rooms
        received["wall_pair"] = wall_pair_rooms
        received["pairs"] = wall_pairs

    worker.finished.connect(_on_finished)
    worker.run()
    assert set(received) == {"polyline", "linework", "wall_pair", "pairs"}
    assert len(received["wall_pair"]) == 1
    assert received["wall_pair"][0].room_id.startswith("ROOM_WALLPAIR_")
    assert len(received["pairs"]) == 4
