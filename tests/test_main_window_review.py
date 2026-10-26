"""MainWindow の単位変更と部屋候補の削除のテスト。"""
import os
import time

import pytest

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from core.models.drawing import Drawing, PolylineElement
from core.parser.dxf_parser import DxfParser
from core.analyzer.room_detector import (
    detect_closed_polyline_room_candidates,
    detect_linework_room_candidates,
)
from core.drawing_viewer.room_overlay import ROOM_ITEM_ROLE
from ui.main_window import MainWindow

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def _ensure_qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _wait_for_detection(window, timeout_s=10.0):
    """部屋検出スレッドの終了を待つ。"""
    deadline = time.monotonic() + timeout_s
    while window._room_thread is not None and time.monotonic() < deadline:
        QTest.qWait(50)
    assert window._room_thread is None, "部屋検出が時間内に終わりませんでした"


def _load_sample_01(window):
    drawing = DxfParser().parse(os.path.join(DATA_DIR, "sample_01_rect.dxf"))
    window._on_load_finished("sample_01_rect.dxf", drawing)
    return drawing


def _detect(window):
    drawing = window._drawing
    window._on_room_detection_finished(
        detect_closed_polyline_room_candidates(drawing),
        detect_linework_room_candidates(drawing),
    )


def test_units_combo_disabled_before_load():
    _ensure_qt_app()
    window = MainWindow()
    assert not window._units_combo.isEnabled()
    window.close()


def test_units_combo_shows_declared_units_after_load():
    _ensure_qt_app()
    window = MainWindow()
    _load_sample_01(window)
    assert window._units_combo.isEnabled()
    assert window._units_combo.currentData() == "mm"
    window.close()


def test_changing_units_recalculates_areas():
    _ensure_qt_app()
    window = MainWindow()
    _load_sample_01(window)
    assert window._rooms == []

    # 単位の宣言を誤ってメートルに変更する：5000x3000 の数値が
    # メートル扱いだと 15,000,000 m² になる。
    window._units_combo.setCurrentIndex(window._units_combo.findData("m"))
    _wait_for_detection(window)
    assert window._drawing.units == "m"
    assert len(window._rooms) == 1
    assert window._rooms[0].area_m2 == pytest.approx(15_000_000.0)

    # 単位を mm に戻すと面積も元に戻る。
    window._units_combo.setCurrentIndex(window._units_combo.findData("mm"))
    _wait_for_detection(window)
    assert window._drawing.units == "mm"
    assert len(window._rooms) == 1
    assert window._rooms[0].area_m2 == pytest.approx(15.0)
    window.close()


def test_room_deletion_removes_overlay_and_disables_export():
    _ensure_qt_app()
    window = MainWindow()
    _load_sample_01(window)
    _detect(window)
    assert len(window._rooms) == 1
    assert window._act_export_rooms.isEnabled()

    room_id = window._rooms[0].room_id
    window._room_panel.select_room(room_id)
    window._room_panel._btn_delete.click()

    assert window._rooms == []
    assert not window._act_export_rooms.isEnabled()
    overlay_items = [
        item for item in window._scene.items() if item.data(ROOM_ITEM_ROLE)
    ]
    assert overlay_items == []
    window.close()


def test_room_deletion_keeps_other_rooms():
    _ensure_qt_app()
    window = MainWindow()
    drawing = DxfParser().parse(os.path.join(DATA_DIR, "sample_02_multi_rect.dxf"))
    window._on_load_finished("sample_02_multi_rect.dxf", drawing)
    _detect(window)
    assert len(window._rooms) == 2

    deleted_id = window._rooms[0].room_id
    window._room_panel.select_room(deleted_id)
    window._room_panel._btn_delete.click()

    assert len(window._rooms) == 1
    assert window._rooms[0].room_id != deleted_id
    assert window._act_export_rooms.isEnabled()
    # 再検出しても削除した部屋は復活しない（セッション内）。
    _detect(window)
    assert len(window._rooms) == 1
    assert window._rooms[0].room_id != deleted_id
    window.close()
