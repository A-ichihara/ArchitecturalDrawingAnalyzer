import pytest

from core.analyzer.room_detector import (
    detect_closed_polyline_room_candidates,
    detect_linework_room_candidates,
    deduplicate_room_candidates,
)
from core.models.drawing import Drawing, LineElement, PolylineElement


def _polyline(element_id, points, *, closed=True, bulges=None, layer="ROOM_BOUNDARY"):
    return PolylineElement(
        element_id=element_id,
        element_type="POLYLINE",
        layer=layer,
        points=points,
        is_closed=closed,
        bulge_list=bulges if bulges is not None else [0.0] * len(points),
    )


def _drawing(elements, units="mm"):
    return Drawing(
        drawing_id="test",
        file_name="test.dxf",
        file_type="dxf",
        units=units,
        elements=elements,
    )


def test_detects_closed_rectangle_and_converts_mm2_to_m2():
    drawing = _drawing([
        _polyline("PL_1", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]])
    ])
    rooms = detect_closed_polyline_room_candidates(drawing)
    assert len(rooms) == 1
    room = rooms[0]
    assert room.room_id == "ROOM_CANDIDATE_000001"
    assert room.room_name == ""
    assert room.area_m2 == pytest.approx(20.0)
    assert room.boundary == [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]
    assert room.wall_type == "unknown"
    assert room.confidence == 0.5
    assert room.properties["source_element_id"] == "PL_1"


def test_skips_open_polyline_and_bulged_polyline():
    drawing = _drawing([
        _polyline("OPEN", [[0, 0], [5000, 0], [5000, 4000]], closed=False),
        _polyline("ARC", [[0, 0], [5000, 0], [5000, 4000]], bulges=[1.0, 0.0, 0.0]),
    ])
    assert detect_closed_polyline_room_candidates(drawing) == []


def test_skips_self_intersecting_and_too_small_polygons():
    drawing = _drawing([
        _polyline("BOW_TIE", [[0, 0], [2000, 2000], [0, 2000], [2000, 0]]),
        _polyline("SMALL", [[0, 0], [500, 0], [500, 500], [0, 500]]),
    ])
    assert detect_closed_polyline_room_candidates(drawing, min_area_m2=1.0) == []


def test_respects_drawing_units():
    drawing = _drawing([
        _polyline("M_RECT", [[0, 0], [5, 0], [5, 4], [0, 4]])
    ], units="m")
    rooms = detect_closed_polyline_room_candidates(drawing)
    assert rooms[0].area_m2 == pytest.approx(20.0)


def test_rejects_invalid_area_threshold_and_unknown_units():
    drawing = _drawing([])
    for invalid in (-1, float("nan"), float("inf"), "invalid", None):
        with pytest.raises(ValueError):
            detect_closed_polyline_room_candidates(drawing, min_area_m2=invalid)
    drawing.units = "drawing_units"
    with pytest.raises(ValueError, match="Unsupported drawing area unit"):
        detect_closed_polyline_room_candidates(drawing)


def test_skips_non_finite_coordinates_without_aborting_other_candidates():
    drawing = _drawing([
        _polyline("BAD", [[0, 0], [float("nan"), 0], [5000, 4000]]),
        _polyline("GOOD", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
    ])
    rooms = detect_closed_polyline_room_candidates(drawing)
    assert len(rooms) == 1
    assert rooms[0].properties["source_element_id"] == "GOOD"


def test_skips_non_finite_bulge_values():
    drawing = _drawing([
        _polyline(
            "BAD_BULGE",
            [[0, 0], [5000, 0], [5000, 4000], [0, 4000]],
            bulges=[0.0, float("nan"), 0.0, 0.0],
        )
    ])
    assert detect_closed_polyline_room_candidates(drawing) == []


def test_skips_malformed_point_without_aborting_other_candidates():
    drawing = _drawing([
        _polyline("BAD_POINT", [[0, 0], [5000], [5000, 4000]]),
        _polyline("GOOD", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
    ])
    rooms = detect_closed_polyline_room_candidates(drawing)
    assert len(rooms) == 1
    assert rooms[0].properties["source_element_id"] == "GOOD"


def test_skips_malformed_bulge_without_aborting_other_candidates():
    drawing = _drawing([
        _polyline(
            "BAD_BULGE",
            [[0, 0], [5000, 0], [5000, 4000], [0, 4000]],
            bulges=[0.0, "not-a-number", 0.0, 0.0],
        ),
        _polyline("GOOD", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
    ])
    rooms = detect_closed_polyline_room_candidates(drawing)
    assert len(rooms) == 1
    assert rooms[0].properties["source_element_id"] == "GOOD"



def _line(element_id, start, end, layer="WALL"):
    return LineElement(
        element_id=element_id,
        element_type="LINE",
        layer=layer,
        start=start,
        end=end,
    )


def test_detects_room_enclosed_by_separate_line_entities():
    drawing = _drawing([
        _line("L1", [0, 0], [5000, 0]),
        _line("L2", [5000, 0], [5000, 4000]),
        _line("L3", [5000, 4000], [0, 4000]),
        _line("L4", [0, 4000], [0, 0]),
    ])
    rooms = detect_linework_room_candidates(drawing)
    assert len(rooms) == 1
    assert rooms[0].area_m2 == pytest.approx(20.0)
    assert rooms[0].room_name == ""
    assert rooms[0].wall_type == "unknown"
    assert rooms[0].confidence == 0.4
    assert set(rooms[0].properties["source_element_ids"]) == {"L1", "L2", "L3", "L4"}


def test_linework_detector_nodes_crossings_and_skips_open_chains():
    drawing = _drawing([
        _line("L1", [0, 0], [5000, 0]),
        _line("L2", [5000, 0], [5000, 4000]),
        _line("L3", [5000, 4000], [0, 4000]),
        _line("L4", [0, 4000], [0, 0]),
        _line("OPEN", [10000, 0], [15000, 0]),
    ])
    rooms = detect_linework_room_candidates(drawing)
    assert len(rooms) == 1
    assert rooms[0].area_m2 == pytest.approx(20.0)


def test_linework_detector_rejects_invalid_threshold_and_unknown_units():
    drawing = _drawing([])
    with pytest.raises(ValueError):
        detect_linework_room_candidates(drawing, min_area_m2=float("nan"))
    drawing.units = "unknown"
    with pytest.raises(ValueError, match="Unsupported drawing area unit"):
        detect_linework_room_candidates(drawing)



def test_linework_detector_finds_two_adjacent_rooms_without_outer_duplicate():
    drawing = _drawing([
        _line("BOTTOM", [0, 0], [10000, 0]),
        _line("TOP", [10000, 4000], [0, 4000]),
        _line("LEFT", [0, 4000], [0, 0]),
        _line("RIGHT", [10000, 0], [10000, 4000]),
        _line("PARTITION", [5000, 0], [5000, 4000]),
    ])
    rooms = detect_linework_room_candidates(drawing)
    assert len(rooms) == 2
    assert sorted(room.area_m2 for room in rooms) == pytest.approx([20.0, 20.0])
    assert all(room.properties["candidate_type"] == "closed_linework" for room in rooms)


def test_linework_detector_skips_malformed_and_zero_length_lines():
    drawing = _drawing([
        _line("L1", [0, 0], [5000, 0]),
        _line("L2", [5000, 0], [5000, 4000]),
        _line("L3", [5000, 4000], [0, 4000]),
        _line("L4", [0, 4000], [0, 0]),
        _line("ZERO", [1, 1], [1, 1]),
        _line("BAD", [0, 0], [float("inf"), 0]),
    ])
    rooms = detect_linework_room_candidates(drawing)
    assert len(rooms) == 1
    assert rooms[0].area_m2 == pytest.approx(20.0)


def test_drawing_element_lookup_returns_matching_element_or_none():
    first = _line("LINE_1", [0, 0], [1000, 0])
    second = _polyline("POLY_2", [[0, 0], [1000, 0], [1000, 1000]])
    drawing = _drawing([first, second])
    assert drawing.get_element_by_id("LINE_1") is first
    assert drawing.get_element_by_id("POLY_2") is second
    assert drawing.get_element_by_id("MISSING") is None


def test_deduplication_keeps_polyline_and_removes_identical_linework():
    drawing = _drawing([
        _polyline("P", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _line("L1", [0, 0], [5000, 0]),
        _line("L2", [5000, 0], [5000, 4000]),
        _line("L3", [5000, 4000], [0, 4000]),
        _line("L4", [0, 4000], [0, 0]),
    ])
    polyline_rooms = detect_closed_polyline_room_candidates(drawing)
    linework_rooms = detect_linework_room_candidates(drawing)
    assert len(polyline_rooms) == len(linework_rooms) == 1
    combined = deduplicate_room_candidates(polyline_rooms, linework_rooms)
    assert len(combined) == 1
    assert combined[0] is polyline_rooms[0]


def test_deduplication_preserves_adjacent_room():
    drawing = _drawing([
        _polyline("P", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _line("L1", [5000, 0], [10000, 0]),
        _line("L2", [10000, 0], [10000, 4000]),
        _line("L3", [10000, 4000], [5000, 4000]),
        _line("L4", [5000, 4000], [5000, 0]),
    ])
    combined = deduplicate_room_candidates(
        detect_closed_polyline_room_candidates(drawing),
        detect_linework_room_candidates(drawing),
    )
    assert len(combined) == 2
    assert sorted(room.area_m2 for room in combined) == pytest.approx([20.0, 20.0])


def test_linework_detector_closes_small_endpoint_gaps():
    drawing = _drawing([
        _line("L1", [0, 0], [5000, 0]),
        _line("L2", [5000.4, 0], [5000, 4000]),
        _line("L3", [5000, 4000], [0, 4000]),
        _line("L4", [0, 4000], [0, 0.3]),
    ])
    rooms = detect_linework_room_candidates(drawing, gap_tolerance=1.0)
    assert len(rooms) == 1
    assert rooms[0].area_m2 == pytest.approx(20.0, rel=0.001)


def test_linework_detector_rejects_invalid_gap_tolerance():
    drawing = _drawing([])
    for invalid in (-1, float("nan"), float("inf"), "invalid", None):
        with pytest.raises(ValueError, match="gap_tolerance"):
            detect_linework_room_candidates(drawing, gap_tolerance=invalid)
