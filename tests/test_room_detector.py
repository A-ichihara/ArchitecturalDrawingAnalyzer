import pytest

from core.analyzer.room_detector import detect_closed_polyline_room_candidates
from core.models.drawing import Drawing, PolylineElement


def _polyline(element_id, points, *, closed=True, bulges=None, layer="ROOM_BOUNDARY"):
    return PolylineElement(
        element_id=element_id,
        element_type="POLYLINE",
        layer=layer,
        points=points,
        is_closed=closed,
        bulge_list=bulges or [0.0] * len(points),
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

    with pytest.raises(ValueError):
        detect_closed_polyline_room_candidates(drawing, min_area_m2=-1)

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
