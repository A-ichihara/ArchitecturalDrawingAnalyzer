from dataclasses import replace

import pytest

from core.analyzer.room_detector import (
    associate_room_names,
    detect_closed_polyline_room_candidates,
    detect_linework_room_candidates,
    deduplicate_room_candidates,
)
from core.models.drawing import Drawing, LineElement, PolylineElement, TextElement


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
    for invalid in (-1, float("nan"), float("inf"), "invalid"):
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


def test_linework_detector_skips_nested_loops_with_ambiguous_hole_areas():
    # A nested loop can represent wall thickness or a shaft rather than a
    # separate room. Room.boundary cannot encode holes, so neither polygon
    # should be emitted with an area that disagrees with its stored boundary.
    drawing = _drawing([
        _line("OUT_BOTTOM", [0, 0], [10000, 0]),
        _line("OUT_RIGHT", [10000, 0], [10000, 10000]),
        _line("OUT_TOP", [10000, 10000], [0, 10000]),
        _line("OUT_LEFT", [0, 10000], [0, 0]),
        _line("IN_BOTTOM", [3000, 3000], [7000, 3000]),
        _line("IN_RIGHT", [7000, 3000], [7000, 7000]),
        _line("IN_TOP", [7000, 7000], [3000, 7000]),
        _line("IN_LEFT", [3000, 7000], [3000, 3000]),
    ])
    assert detect_linework_room_candidates(drawing) == []


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
    for invalid in (-1, float("nan"), float("inf"), "invalid"):
        with pytest.raises(ValueError, match="gap_tolerance"):
            detect_linework_room_candidates(drawing, gap_tolerance=invalid)



def test_default_gap_tolerance_is_equivalent_to_one_millimetre_for_metre_drawings():
    drawing = _drawing([
        _line("L1", [0, 0], [5, 0]),
        _line("L2", [5.0004, 0], [5, 4]),
        _line("L3", [5, 4], [0, 4]),
        _line("L4", [0, 4], [0, 0.0003]),
    ], units="m")
    rooms = detect_linework_room_candidates(drawing)
    assert len(rooms) == 1
    assert rooms[0].area_m2 == pytest.approx(20.0, rel=0.001)


def test_linework_detector_does_not_close_gaps_larger_than_tolerance():
    drawing = _drawing([
        _line("L1", [0, 0], [5000, 0]),
        _line("L2", [5002, 0], [5000, 4000]),
        _line("L3", [5000, 4000], [0, 4000]),
        _line("L4", [0, 4000], [0, 0]),
    ])
    assert detect_linework_room_candidates(drawing, gap_tolerance=1.0) == []


def test_linework_detector_zero_tolerance_disables_endpoint_snapping():
    drawing = _drawing([
        _line("L1", [0, 0], [5000, 0]),
        _line("L2", [5000.4, 0], [5000, 4000]),
        _line("L3", [5000, 4000], [0, 4000]),
        _line("L4", [0, 4000], [0, 0]),
    ])
    assert detect_linework_room_candidates(drawing, gap_tolerance=0) == []


def test_none_gap_tolerance_uses_unit_aware_default():
    drawing = _drawing([
        _line("L1", [0, 0], [5000, 0]),
        _line("L2", [5000.4, 0], [5000, 4000]),
        _line("L3", [5000, 4000], [0, 4000]),
        _line("L4", [0, 4000], [0, 0.3]),
    ])
    assert len(detect_linework_room_candidates(drawing, gap_tolerance=None)) == 1



def _text(element_id, text, point, *, element_type="TEXT"):
    return TextElement(
        element_id=element_id,
        element_type=element_type,
        layer="ROOM_LABELS",
        text=text,
        insertion_point=point,
    )


def test_associates_one_text_label_inside_room_candidate():
    drawing = _drawing([
        _polyline("ROOM", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _text("LABEL", "事務室", [2500, 2000]),
    ])
    rooms = detect_closed_polyline_room_candidates(drawing)
    associated = associate_room_names(drawing, rooms)
    assert associated[0].room_name == "事務室"
    assert associated[0].properties["room_name_source_element_id"] == "LABEL"
    assert rooms[0].room_name == ""  # original candidate is not mutated


def test_room_name_association_leaves_multiple_labels_unnamed():
    drawing = _drawing([
        _polyline("ROOM", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _text("LABEL1", "事務室", [2000, 2000]),
        _text("LABEL2", "管理室", [3000, 2000]),
    ])
    rooms = detect_closed_polyline_room_candidates(drawing)
    associated = associate_room_names(drawing, rooms)
    assert associated[0].room_name == ""


def test_room_name_association_ignores_numeric_text_and_boundary_points():
    drawing = _drawing([
        _polyline("ROOM", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _text("AREA", "20.00㎡", [2000, 2000]),
        _text("EDGE", "事務室", [0, 2000]),
    ])
    rooms = detect_closed_polyline_room_candidates(drawing)
    associated = associate_room_names(drawing, rooms)
    assert associated[0].room_name == ""


def test_room_name_association_does_not_guess_for_overlapping_candidates():
    drawing = _drawing([
        _polyline("ROOM1", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _polyline("ROOM2", [[1000, 1000], [4000, 1000], [4000, 3000], [1000, 3000]]),
        _text("LABEL", "事務室", [2500, 2000]),
    ])
    rooms = detect_closed_polyline_room_candidates(drawing)
    associated = associate_room_names(drawing, rooms)
    assert all(room.room_name == "" for room in associated)



def test_associates_mtext_after_normalizing_paragraph_breaks():
    drawing = _drawing([
        _polyline("ROOM", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _text("MTEXT_LABEL", "事務室\\P（受付）", [2500, 2000], element_type="MTEXT"),
    ])
    rooms = detect_closed_polyline_room_candidates(drawing)
    associated = associate_room_names(drawing, rooms)
    assert associated[0].room_name == "事務室 （受付）"
    assert associated[0].properties["room_name_source_element_id"] == "MTEXT_LABEL"


def test_room_name_association_handles_duplicate_room_ids_independently():
    drawing = _drawing([
        _polyline("ROOM1", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _polyline("ROOM2", [[6000, 0], [11000, 0], [11000, 4000], [6000, 4000]]),
        _text("LABEL1", "事務室", [2500, 2000]),
        _text("LABEL2", "会議室", [8500, 2000]),
    ])
    rooms = detect_closed_polyline_room_candidates(drawing)
    rooms = [replace(room, room_id="DUPLICATE_ID") for room in rooms]
    associated = associate_room_names(drawing, rooms)
    assert [room.room_name for room in associated] == ["事務室", "会議室"]


def test_room_name_association_skips_malformed_text_coordinates():
    drawing = _drawing([
        _polyline("ROOM", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _text("BAD_LABEL", "事務室", ["not-a-coordinate", 2000]),
    ])
    rooms = detect_closed_polyline_room_candidates(drawing)
    associated = associate_room_names(drawing, rooms)
    assert associated[0].room_name == ""



def test_associates_text_with_linework_room_candidate():
    drawing = _drawing([
        _line("BOTTOM", [0, 0], [5000, 0]),
        _line("RIGHT", [5000, 0], [5000, 4000]),
        _line("TOP", [5000, 4000], [0, 4000]),
        _line("LEFT", [0, 4000], [0, 0]),
        _text("LABEL", "会議室", [2500, 2000]),
    ])
    rooms = detect_linework_room_candidates(drawing)
    associated = associate_room_names(drawing, rooms)
    assert len(associated) == 1
    assert associated[0].room_name == "会議室"
    assert associated[0].properties["room_name_source_element_id"] == "LABEL"


def test_room_name_association_preserves_existing_room_properties():
    drawing = _drawing([
        _polyline("ROOM", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _text("LABEL", "事務室", [2500, 2000]),
    ])
    rooms = detect_closed_polyline_room_candidates(drawing)
    rooms[0].properties["custom_marker"] = "keep"
    associated = associate_room_names(drawing, rooms)
    assert associated[0] is not rooms[0]
    assert associated[0].properties["custom_marker"] == "keep"
    assert "room_name_source_element_id" not in rooms[0].properties
    assert "room_name_association" not in rooms[0].properties


def test_room_name_association_ignores_empty_and_whitespace_text():
    drawing = _drawing([
        _polyline("ROOM", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _text("EMPTY", "   ", [2000, 2000]),
    ])
    rooms = detect_closed_polyline_room_candidates(drawing)
    associated = associate_room_names(drawing, rooms)
    assert associated[0].room_name == ""

@pytest.mark.parametrize(
    "point",
    [[float("nan"), 2000], [2500, float("inf")], [float("-inf"), 2000]],
)
def test_room_name_association_skips_non_finite_text_coordinates(point):
    drawing = _drawing([
        _polyline("ROOM", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _text("BAD_LABEL", "事務室", point),
    ])
    rooms = detect_closed_polyline_room_candidates(drawing)
    associated = associate_room_names(drawing, rooms)
    assert len(associated) == 1
    assert associated[0].room_name == ""

def test_room_name_association_does_not_choose_between_two_labels():
    drawing = _drawing([
        _polyline("ROOM", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _text("LABEL_A", "事務室", [2000, 2000]),
        _text("LABEL_B", "倉庫", [3000, 2000]),
    ])
    rooms = detect_closed_polyline_room_candidates(drawing)

    associated = associate_room_names(drawing, rooms)

    assert len(associated) == 1
    assert associated[0].room_name == ""
    assert "room_name_source_element_id" not in associated[0].properties


def test_room_name_association_ignores_text_on_candidate_boundary():
    drawing = _drawing([
        _polyline("ROOM", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _text("LABEL", "事務室", [0, 2000]),
    ])
    rooms = detect_closed_polyline_room_candidates(drawing)

    associated = associate_room_names(drawing, rooms)

    assert associated[0].room_name == ""


def test_room_name_association_ignores_numeric_dimension_text():
    drawing = _drawing([
        _polyline("ROOM", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _text("AREA", "20.00㎡", [2500, 2000]),
    ])
    rooms = detect_closed_polyline_room_candidates(drawing)

    associated = associate_room_names(drawing, rooms)

    assert associated[0].room_name == ""


def test_room_name_association_does_not_guess_for_overlapping_candidates():
    drawing = _drawing([
        _polyline("ROOM_A", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _polyline("ROOM_B", [[1000, 1000], [6000, 1000], [6000, 5000], [1000, 5000]]),
        _text("LABEL", "事務室", [2500, 2000]),
    ])
    rooms = detect_closed_polyline_room_candidates(drawing)

    associated = associate_room_names(drawing, rooms)

    assert len(associated) == 2
    assert all(room.room_name == "" for room in associated)



@pytest.mark.parametrize(
    ("units", "width", "height", "horizontal_gap", "vertical_gap"),
    [
        ("cm", 500, 400, 0.04, 0.03),
        ("in", 200, 160, 0.02, 0.01),
        ("ft", 20, 16, 0.001, 0.001),
    ],
)
def test_default_gap_tolerance_is_one_millimetre_for_other_supported_units(
    units, width, height, horizontal_gap, vertical_gap
):
    drawing = _drawing([
        _line("BOTTOM", [0, 0], [width, 0]),
        _line("RIGHT", [width + horizontal_gap, 0], [width, height]),
        _line("TOP", [width, height], [0, height]),
        _line("LEFT", [0, height], [0, vertical_gap]),
    ], units=units)

    rooms = detect_linework_room_candidates(drawing)

    assert len(rooms) == 1
    expected_area_m2 = width * height * {
        "cm": 1e-4,
        "in": 0.0254**2,
        "ft": 0.3048**2,
    }[units]
    assert rooms[0].area_m2 == pytest.approx(expected_area_m2, rel=0.01)


def test_endpoint_snapping_does_not_chain_points_beyond_tolerance():
    # The distractor endpoint is within tolerance of both room corners, but
    # the two corners are farther apart than tolerance. It must not bridge
    # the gap and manufacture a closed room.
    drawing = _drawing([
        _line("BOTTOM", [0, 0], [5000, 0]),
        _line("RIGHT", [5001.5, 0], [5001.5, 4000]),
        _line("TOP", [5001.5, 4000], [0, 4000]),
        _line("LEFT", [0, 4000], [0, 0]),
        _line("DISTRACTOR", [5000.75, 0], [5000.75, -1000]),
    ])

    assert detect_linework_room_candidates(drawing, gap_tolerance=1.0) == []


def test_linework_detector_skips_close_concentric_wall_outlines():
    """Double-line wall outlines must not invent a usable room area."""
    drawing = _drawing([
        _line("OUT_BOTTOM", [0, 0], [10000, 0]),
        _line("OUT_RIGHT", [10000, 0], [10000, 8000]),
        _line("OUT_TOP", [10000, 8000], [0, 8000]),
        _line("OUT_LEFT", [0, 8000], [0, 0]),
        _line("IN_BOTTOM", [150, 150], [9850, 150]),
        _line("IN_RIGHT", [9850, 150], [9850, 7850]),
        _line("IN_TOP", [9850, 7850], [150, 7850]),
        _line("IN_LEFT", [150, 7850], [150, 150]),
    ])
    assert detect_linework_room_candidates(drawing) == []


def test_linework_detector_preserves_adjacent_rooms_with_dangling_wall_lines():
    """Unclosed nearby wall fragments must not erase two valid adjacent rooms."""
    drawing = _drawing([
        _line("BOTTOM", [0, 0], [10000, 0]),
        _line("TOP", [10000, 4000], [0, 4000]),
        _line("LEFT", [0, 4000], [0, 0]),
        _line("RIGHT", [10000, 0], [10000, 4000]),
        _line("PARTITION", [5000, 0], [5000, 4000]),
        _line("DANGLING", [12000, 0], [14000, 0]),
    ])
    rooms = detect_linework_room_candidates(drawing)
    assert len(rooms) == 2
    assert sorted(room.area_m2 for room in rooms) == pytest.approx([20.0, 20.0])


def test_linework_detector_skips_nested_loops_even_with_interior_text():
    """Text within a shaft-like nested loop must not turn it into a room."""
    drawing = _drawing([
        _line("OUT_BOTTOM", [0, 0], [10000, 0]),
        _line("OUT_RIGHT", [10000, 0], [10000, 10000]),
        _line("OUT_TOP", [10000, 10000], [0, 10000]),
        _line("OUT_LEFT", [0, 10000], [0, 0]),
        _line("IN_BOTTOM", [3000, 3000], [7000, 3000]),
        _line("IN_RIGHT", [7000, 3000], [7000, 7000]),
        _line("IN_TOP", [7000, 7000], [3000, 7000]),
        _line("IN_LEFT", [3000, 7000], [3000, 3000]),
        TextElement(
            element_id="SHAFT_LABEL",
            element_type="TEXT",
            layer="ROOM_LABELS",
            text="PS",
            insertion_point=[5000, 5000],
        ),
    ])
    rooms = detect_linework_room_candidates(drawing)
    assert associate_room_names(drawing, rooms) == []


def test_linework_detector_keeps_adjacent_rooms_with_text_on_shared_wall():
    """A label on a shared wall is not assigned to either neighboring room."""
    drawing = _drawing([
        _line("BOTTOM", [0, 0], [10000, 0]),
        _line("TOP", [10000, 4000], [0, 4000]),
        _line("LEFT", [0, 4000], [0, 0]),
        _line("RIGHT", [10000, 0], [10000, 4000]),
        _line("PARTITION", [5000, 0], [5000, 4000]),
        TextElement(
            element_id="WALL_LABEL",
            element_type="TEXT",
            layer="ROOM_LABELS",
            text="会議室",
            insertion_point=[5000, 2000],
        ),
    ])
    rooms = associate_room_names(drawing, detect_linework_room_candidates(drawing))
    assert len(rooms) == 2
    assert all(room.room_name == "" for room in rooms)


def test_deduplication_handles_reversed_polyline_vertex_order():
    """A coincident LINE room must not duplicate a reversed polyline room."""
    drawing = _drawing([
        _polyline("P", [[0, 0], [0, 4000], [5000, 4000], [5000, 0]]),
        _line("L1", [0, 0], [5000, 0]),
        _line("L2", [5000, 0], [5000, 4000]),
        _line("L3", [5000, 4000], [0, 4000]),
        _line("L4", [0, 4000], [0, 0]),
    ])
    polyline_rooms = detect_closed_polyline_room_candidates(drawing)
    linework_rooms = detect_linework_room_candidates(drawing)
    combined = deduplicate_room_candidates(polyline_rooms, linework_rooms)
    assert len(polyline_rooms) == len(linework_rooms) == 1
    assert len(combined) == 1
    assert combined[0] is polyline_rooms[0]


def test_deduplication_does_not_remove_partially_overlapping_rooms():
    """Overlap alone must not be treated as identical geometry."""
    drawing = _drawing([
        _polyline("P", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _line("L1", [2500, 0], [7500, 0]),
        _line("L2", [7500, 0], [7500, 4000]),
        _line("L3", [7500, 4000], [2500, 4000]),
        _line("L4", [2500, 4000], [2500, 0]),
    ])
    combined = deduplicate_room_candidates(
        detect_closed_polyline_room_candidates(drawing),
        detect_linework_room_candidates(drawing),
    )
    assert len(combined) == 2
    assert sorted(room.area_m2 for room in combined) == pytest.approx([20.0, 20.0])


def test_deduplication_keeps_adjacent_rooms_with_shared_boundary():
    """Sharing a wall is not geometric duplication."""
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


def test_deduplication_keeps_adjacent_rooms_and_removes_only_matching_linework():
    """A coincident LINE outline is redundant, but its neighbor is not."""
    drawing = _drawing([
        _polyline("P", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        _line("BOTTOM", [0, 0], [10000, 0]),
        _line("RIGHT", [10000, 0], [10000, 4000]),
        _line("TOP", [10000, 4000], [0, 4000]),
        _line("LEFT", [0, 4000], [0, 0]),
        _line("PARTITION", [5000, 0], [5000, 4000]),
    ])
    polyline_rooms = detect_closed_polyline_room_candidates(drawing)
    linework_rooms = detect_linework_room_candidates(drawing)
    combined = deduplicate_room_candidates(polyline_rooms, linework_rooms)
    assert len(polyline_rooms) == 1
    assert len(linework_rooms) == 2
    assert len(combined) == 2
    assert combined[0] is polyline_rooms[0]
    assert sorted(room.area_m2 for room in combined) == pytest.approx([20.0, 20.0])



def test_closed_polyline_removes_repeated_final_vertex_before_storing_boundary():
    """DXF rings that repeat their first vertex should not store it twice."""
    drawing = _drawing([
        _polyline(
            "CLOSED_WITH_REPEAT",
            [[0, 0], [5000, 0], [5000, 4000], [0, 4000], [0, 0]],
        )
    ])
    rooms = detect_closed_polyline_room_candidates(drawing)
    assert len(rooms) == 1
    assert rooms[0].area_m2 == pytest.approx(20.0)
    assert rooms[0].boundary == [
        [0, 0], [5000, 0], [5000, 4000], [0, 4000]
    ]


def test_closed_polyline_includes_candidate_equal_to_minimum_area_threshold():
    """The minimum area threshold is inclusive, not a strict lower bound."""
    drawing = _drawing([
        _polyline("ROOM_1M2", [[0, 0], [1000, 0], [1000, 1000], [0, 1000]])
    ])
    rooms = detect_closed_polyline_room_candidates(drawing, min_area_m2=1.0)
    assert len(rooms) == 1
    assert rooms[0].area_m2 == pytest.approx(1.0)


def test_linework_detector_skips_non_finite_lines_without_losing_valid_room():
    """Malformed or non-finite line entities should not poison valid geometry."""
    drawing = _drawing([
        _line("NAN_LINE", [float("nan"), 0], [1000, 0]),
        _line("SHORT_START", [0], [1000, 0]),
        _line("L1", [0, 0], [5000, 0]),
        _line("L2", [5000, 0], [5000, 4000]),
        _line("L3", [5000, 4000], [0, 4000]),
        _line("L4", [0, 4000], [0, 0]),
    ])
    rooms = detect_linework_room_candidates(drawing)
    assert len(rooms) == 1
    assert rooms[0].area_m2 == pytest.approx(20.0)


def test_deduplication_removes_duplicate_linework_candidates_too():
    """Exact duplicates within linework results should only be returned once."""
    drawing = _drawing([
        _line("L1", [0, 0], [5000, 0]),
        _line("L2", [5000, 0], [5000, 4000]),
        _line("L3", [5000, 4000], [0, 4000]),
        _line("L4", [0, 4000], [0, 0]),
    ])
    rooms = detect_linework_room_candidates(drawing)
    assert len(rooms) == 1
    duplicate = replace(rooms[0], room_id="DUPLICATE_ROOM_ID")
    combined = deduplicate_room_candidates([], [rooms[0], duplicate])
    assert len(combined) == 1
    assert combined[0] is rooms[0]



def test_room_name_association_does_not_collapse_candidates_with_duplicate_ids():
    """Distinct overlapping candidates remain ambiguous even if their IDs match."""
    drawing = _drawing([
        TextElement(
            element_id="LABEL",
            element_type="TEXT",
            layer="ROOM_LABELS",
            text="会議室",
            insertion_point=[2500, 2000],
        )
    ])
    first = RoomLike = detect_closed_polyline_room_candidates(
        _drawing([_polyline("A", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]])])
    )[0]
    second = replace(first, room_id=first.room_id)
    associated = associate_room_names(drawing, [first, second])
    assert len(associated) == 2
    assert all(room.room_name == "" for room in associated)


def test_room_name_association_normalizes_mtext_line_break_and_ignores_numeric_text():
    """MTEXT paragraph codes are normalized; dimensions are not room names."""
    drawing = _drawing([
        _polyline("ROOM", [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]),
        TextElement(
            element_id="AREA",
            element_type="TEXT",
            layer="DIMENSIONS",
            text="20.00㎡",
            insertion_point=[1000, 1000],
        ),
        TextElement(
            element_id="NAME",
            element_type="MTEXT",
            layer="ROOM_LABELS",
            text="機械室\\P空調機械",
            insertion_point=[2500, 2000],
        ),
    ])
    rooms = associate_room_names(
        drawing, detect_closed_polyline_room_candidates(drawing)
    )
    assert len(rooms) == 1
    assert rooms[0].room_name == "機械室 空調機械"
    assert rooms[0].properties["room_name_source_element_id"] == "NAME"
