"""部屋一覧パネル（確認・修正 UI）のテスト。"""
import os

import pytest

from core.models.room import (
    REVIEW_STATUS_CONFIRMED,
    REVIEW_STATUS_REJECTED,
    Room,
)
from ui.panels.room_panel import RoomPanel


def _ensure_qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _rooms():
    return [
        Room(
            room_id="ROOM_CANDIDATE_000001",
            room_name="和室",
            area_m2=10.5,
            boundary=[[0, 0], [3000, 0], [3000, 3500], [0, 3500]],
            confidence=0.5,
            properties={"candidate_type": "closed_straight_polyline"},
        ),
        Room(
            room_id="ROOM_CANDIDATE_000002",
            room_name="",
            area_m2=20.0,
            boundary=[[3000, 0], [8000, 0], [8000, 4000], [3000, 4000]],
            confidence=0.4,
            properties={"candidate_type": "closed_linework"},
        ),
    ]


def test_panel_lists_rooms_with_status():
    _ensure_qt_app()
    panel = RoomPanel()
    panel.set_rooms(_rooms())

    assert panel._room_list.count() == 2
    assert panel._room_list.item(0).text() == "1. 和室 — 10.50 m² [要確認]"
    assert panel._room_list.item(1).text() == "2. （未判定） — 20.00 m² [要確認]"


def test_panel_select_emits_room_and_shows_editor():
    _ensure_qt_app()
    panel = RoomPanel()
    rooms = _rooms()
    panel.set_rooms(rooms)
    selected = []
    panel.room_selected.connect(selected.append)

    panel.select_room("ROOM_CANDIDATE_000002")
    assert selected == ["ROOM_CANDIDATE_000002"]
    assert panel._name_edit.text() == ""
    assert "20.00 m²" in panel._info_label.text()
    assert panel._name_edit.isEnabled()


def test_panel_name_edit_emits_change():
    _ensure_qt_app()
    panel = RoomPanel()
    rooms = _rooms()
    panel.set_rooms(rooms)
    panel.show_room(rooms[0])
    changed = []
    panel.room_name_changed.connect(lambda room_id, name: changed.append((room_id, name)))

    panel._name_edit.setText("会議室")
    panel._name_edit.editingFinished.emit()
    assert changed == [("ROOM_CANDIDATE_000001", "会議室")]
    assert rooms[0].room_name == "会議室"
    assert panel._room_list.item(0).text().startswith("1. 会議室")


def test_panel_status_buttons_emit_change():
    _ensure_qt_app()
    panel = RoomPanel()
    rooms = _rooms()
    panel.set_rooms(rooms)
    panel.show_room(rooms[0])
    changed = []
    panel.room_status_changed.connect(lambda room_id, status: changed.append((room_id, status)))

    panel._btn_confirm.click()
    assert changed == [("ROOM_CANDIDATE_000001", REVIEW_STATUS_CONFIRMED)]
    assert rooms[0].review_status == REVIEW_STATUS_CONFIRMED
    assert "[確定]" in panel._room_list.item(0).text()

    panel._btn_reject.click()
    assert changed[-1] == ("ROOM_CANDIDATE_000001", REVIEW_STATUS_REJECTED)
    assert "[却下]" in panel._room_list.item(0).text()


def test_panel_clear_resets():
    _ensure_qt_app()
    panel = RoomPanel()
    panel.set_rooms(_rooms())
    panel.clear()
    assert panel._room_list.count() == 0
    assert not panel._name_edit.isEnabled()
    assert "まだ検出されていません" in panel._info_label.text()
