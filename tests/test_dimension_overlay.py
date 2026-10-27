"""DimensionOverlayRenderer のテスト。"""
import os

import pytest
from PySide6.QtWidgets import QApplication

from core.analyzer.dimension_check import DimensionCheck, check_dimensions
from core.drawing_viewer.dimension_overlay import (
    DIMENSION_ITEM_ROLE,
    DimensionOverlayRenderer,
    dimension_detail_text,
    dimension_label_text,
)
from core.drawing_viewer.scene import DrawingScene
from core.parser.pdf_parser import PdfParser
from tests.test_pdf_parser import _make_two_room_pdf


def _ensure_qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _make_checks(tmp_path):
    pdf_path = os.path.join(tmp_path, "two_rooms.pdf")
    _make_two_room_pdf(pdf_path)
    drawing = PdfParser().parse(pdf_path, scale_mm_per_pt=10.0)
    checks = check_dimensions(drawing)
    assert len(checks) == 2
    return drawing, checks


def test_render_checks_draws_markers_by_status(tmp_path):
    _ensure_qt_app()
    drawing, checks = _make_checks(tmp_path)
    scene = DrawingScene()
    renderer = DimensionOverlayRenderer()

    rendered = renderer.render_checks(checks, drawing, scene)

    assert set(rendered) == {"DIM001", "DIM002"}
    for check in checks:
        group = rendered[check.dimension_id]
        assert group.data(DIMENSION_ITEM_ROLE) == check.dimension_id
        assert group.isVisible()
    # 印の色が状態ごとに違う（一致＝緑、不一致＝赤）。
    matched = next(c for c in checks if c.status == "matched")
    mismatched = next(c for c in checks if c.status == "mismatched")
    matched_pen = rendered[matched.dimension_id].childItems()[0].pen().color().name()
    mismatched_pen = rendered[mismatched.dimension_id].childItems()[0].pen().color().name()
    assert matched_pen == "#9ece6a"
    assert mismatched_pen == "#f7768e"


def test_render_checks_shows_value_and_measured_length(tmp_path):
    _ensure_qt_app()
    drawing, checks = _make_checks(tmp_path)
    scene = DrawingScene()
    renderer = DimensionOverlayRenderer()

    rendered = renderer.render_checks(checks, drawing, scene)

    mismatched = next(c for c in checks if c.status == "mismatched")
    label = rendered[mismatched.dimension_id].childItems()[1].text()
    assert label == "2000 / 2040"
    detail = dimension_detail_text(mismatched)
    assert "2000" in detail and "2040" in detail and "不一致" in detail
    assert dimension_label_text(mismatched) == "2000 / 2040"


def test_set_visible_toggles_markers(tmp_path):
    _ensure_qt_app()
    drawing, checks = _make_checks(tmp_path)
    scene = DrawingScene()
    renderer = DimensionOverlayRenderer()
    rendered = renderer.render_checks(checks, drawing, scene)

    renderer.set_visible(False)
    assert all(not g.isVisible() for g in rendered.values())
    renderer.set_visible(True)
    assert all(g.isVisible() for g in rendered.values())


def test_clear_removes_markers(tmp_path):
    _ensure_qt_app()
    drawing, checks = _make_checks(tmp_path)
    scene = DrawingScene()
    renderer = DimensionOverlayRenderer()
    renderer.render_checks(checks, drawing, scene)
    assert len(renderer._items) == 2

    renderer.clear(scene)

    assert renderer._items == {}
    remaining = [
        item for item in scene.items()
        if item.data(DIMENSION_ITEM_ROLE) is not None
    ]
    assert remaining == []


def test_check_without_dimension_line_is_skipped(tmp_path):
    _ensure_qt_app()
    drawing, checks = _make_checks(tmp_path)
    orphan = DimensionCheck(
        dimension_id="DIM999", value_mm=1000.0, dimension_text="1000",
        status="not_determinable", confidence=0.9,
        dimension_line_id="存在しない要素",
    )
    scene = DrawingScene()
    renderer = DimensionOverlayRenderer()

    rendered = renderer.render_checks([orphan], drawing, scene)

    assert rendered == {}


def test_label_without_measured_length(tmp_path):
    check = DimensionCheck(
        dimension_id="DIM001", value_mm=4000.0, dimension_text="4000",
        status="not_determinable", confidence=0.9,
    )
    assert dimension_label_text(check) == "4000 / ―"
    assert "判定不能" in dimension_detail_text(check)
