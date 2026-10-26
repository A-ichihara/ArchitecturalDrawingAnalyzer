"""部屋オーバーレイ描画と MainWindow への組み込みテスト。"""
import os

import pytest

from core.analyzer.room_detector import (
    associate_room_names,
    deduplicate_room_candidates,
    detect_closed_polyline_room_candidates,
    detect_linework_room_candidates,
)
from core.drawing_viewer.room_overlay import (
    ROOM_ITEM_ROLE,
    RoomOverlayRenderer,
    room_label_text,
)
from core.drawing_viewer.scene import DrawingScene
from core.models.room import REVIEW_STATUS_CONFIRMED, REVIEW_STATUS_REJECTED, Room
from core.parser.dxf_parser import DxfParser

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def _ensure_qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _sample_rooms(filename):
    drawing = DxfParser().parse(os.path.join(DATA_DIR, filename))
    polyline_rooms = detect_closed_polyline_room_candidates(drawing)
    linework_rooms = detect_linework_room_candidates(drawing)
    rooms = deduplicate_room_candidates(polyline_rooms, linework_rooms)
    return drawing, associate_room_names(drawing, rooms)


def _analysis_items(scene):
    """シーン上の部屋オーバーレイ（部屋 ID を持つトップレベル項目）を返す。"""
    return [item for item in scene.items() if item.data(ROOM_ITEM_ROLE)]


def test_overlay_renders_polygon_and_label_per_room():
    _ensure_qt_app()
    _, rooms = _sample_rooms("sample_02_multi_rect.dxf")
    assert len(rooms) == 2

    scene = DrawingScene()
    rendered = RoomOverlayRenderer().render_rooms(rooms, scene)

    assert set(rendered) == {r.room_id for r in rooms}
    assert len(_analysis_items(scene)) == 2
    for room in rooms:
        group = rendered[room.room_id]
        assert group.data(ROOM_ITEM_ROLE) == room.room_id
        children = group.childItems()
        assert len(children) == 2
        polygon, label = children
        # 境界矩形の面積が部屋面積（mm²）と一致する。
        rect = polygon.boundingRect()
        assert rect.width() * rect.height() == pytest.approx(room.area_m2 * 1e6, rel=0.01)
        assert f"{room.area_m2:.2f} m²" in label.text()
        assert room_label_text(room).startswith("（未判定）")


def test_overlay_colours_follow_review_status():
    _ensure_qt_app()
    _, rooms = _sample_rooms("sample_02_multi_rect.dxf")
    rooms[0].review_status = REVIEW_STATUS_CONFIRMED
    rooms[1].review_status = REVIEW_STATUS_REJECTED

    scene = DrawingScene()
    renderer = RoomOverlayRenderer()
    rendered = renderer.render_rooms(rooms, scene)

    from PySide6.QtCore import Qt

    confirmed_polygon = rendered[rooms[0].room_id].childItems()[0]
    assert confirmed_polygon.pen().color().name() == "#9ece6a"
    rejected_polygon = rendered[rooms[1].room_id].childItems()[0]
    assert rejected_polygon.pen().color().name() == "#565f89"
    assert rejected_polygon.pen().style() == Qt.PenStyle.DashLine


def test_overlay_skips_invalid_boundary_and_clears():
    _ensure_qt_app()
    bad = Room(room_id="BAD", room_name="", area_m2=0.0, boundary=[[0, 0], [1, 1]])
    _, rooms = _sample_rooms("sample_01_rect.dxf")

    scene = DrawingScene()
    renderer = RoomOverlayRenderer()
    rendered = renderer.render_rooms([bad] + rooms, scene)
    assert set(rendered) == {rooms[0].room_id}
    assert len(_analysis_items(scene)) == 1

    renderer.clear(scene)
    assert _analysis_items(scene) == []


def test_overlay_items_are_selectable_and_hideable():
    """オーバーレイ項目はクリック選択でき、表示/非表示も切り替えられる。"""
    _ensure_qt_app()
    _, rooms = _sample_rooms("sample_01_rect.dxf")

    scene = DrawingScene()
    renderer = RoomOverlayRenderer()
    rendered = renderer.render_rooms(rooms, scene)
    group = rendered[rooms[0].room_id]

    group.setSelected(True)
    assert group.isSelected()
    assert group in scene.selectedItems()

    renderer.set_visible(False)
    assert not group.isVisible()
    renderer.set_visible(True)
    assert group.isVisible()


def test_main_window_detection_renders_overlay_and_enables_export():
    _ensure_qt_app()
    from ui.main_window import MainWindow

    _, rooms = _sample_rooms("sample_01_rect.dxf")
    window = MainWindow()
    assert not window._act_export_rooms.isEnabled()

    window._on_room_detection_finished(rooms, [])
    assert window._rooms == rooms
    assert len(_analysis_items(window._scene)) == 1
    assert window._act_export_rooms.isEnabled()
    assert window._room_panel._room_list.count() == 1
    window.close()
