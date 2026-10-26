"""部屋の確認内容の保存・復元（サイドカー）のテスト。"""
import json
import os

from core.models.room import (
    REVIEW_STATUS_CONFIRMED,
    REVIEW_STATUS_REJECTED,
    REVIEW_STATUS_TO_CONFIRM,
    Room,
)
from core.rooms.review_store import (
    apply_reviews,
    load_reviews,
    save_reviews,
    sidecar_path,
)


def _room(room_id, name="", status=REVIEW_STATUS_TO_CONFIRM):
    room = Room(
        room_id=room_id,
        room_name=name,
        area_m2=10.0,
        boundary=[[0, 0], [3000, 0], [3000, 3500], [0, 3500]],
    )
    room.review_status = status
    return room


def test_sidecar_path_is_next_to_dxf():
    assert sidecar_path("/drawings/plan.dxf") == "/drawings/plan.rooms.json"
    assert sidecar_path("/drawings/plan.DXF") == "/drawings/plan.rooms.json"


def test_save_load_round_trip_only_touched_rooms(tmp_path):
    dxf = tmp_path / "plan.dxf"
    dxf.write_text("", encoding="utf-8")
    rooms = [
        _room("ROOM_CANDIDATE_000001", "会議室", REVIEW_STATUS_CONFIRMED),
        _room("ROOM_CANDIDATE_000002", "和室", REVIEW_STATUS_TO_CONFIRM),
        _room("ROOM_CANDIDATE_000003", "", REVIEW_STATUS_REJECTED),
    ]
    # 触ったのは 1 件目と 3 件目だけ。2 件目の自動関連付け名は保存しない。
    path = save_reviews(str(dxf), rooms, {"ROOM_CANDIDATE_000001", "ROOM_CANDIDATE_000003"})
    assert path == sidecar_path(str(dxf))
    assert os.path.exists(path)

    loaded = load_reviews(str(dxf))
    assert loaded == {
        "ROOM_CANDIDATE_000001": {"room_name": "会議室", "review_status": "confirmed"},
        "ROOM_CANDIDATE_000003": {"review_status": "rejected"},
    }


def test_load_returns_empty_without_file_or_with_broken_file(tmp_path):
    dxf = tmp_path / "plan.dxf"
    assert load_reviews(str(dxf)) == {}
    sidecar = tmp_path / "plan.rooms.json"
    sidecar.write_text("{壊れた json", encoding="utf-8")
    assert load_reviews(str(dxf)) == {}
    sidecar.write_text(json.dumps({"rooms": "not-a-dict"}), encoding="utf-8")
    assert load_reviews(str(dxf)) == {}


def test_apply_reviews_restores_name_and_status():
    rooms = [_room("ROOM_CANDIDATE_000001"), _room("ROOM_CANDIDATE_000002", "既存名")]
    reviews = {
        "ROOM_CANDIDATE_000001": {"room_name": "会議室", "review_status": "confirmed"},
        "ROOM_CANDIDATE_000002": {"review_status": "bogus-status"},
        "ROOM_CANDIDATE_999999": {"room_name": "存在しない部屋"},
    }
    assert apply_reviews(rooms, reviews) == 2
    assert rooms[0].room_name == "会議室"
    assert rooms[0].review_status == REVIEW_STATUS_CONFIRMED
    # 不明な状態値は無視され、部屋名はそのまま残る。
    assert rooms[1].room_name == "既存名"
    assert rooms[1].review_status == REVIEW_STATUS_TO_CONFIRM


def test_main_window_saves_and_restores_reviews(tmp_path):
    """検出→名前編集→再検出で、保存した確認内容が復元されること。"""
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from core.analyzer.room_detector import (
        associate_room_names,
        deduplicate_room_candidates,
        detect_closed_polyline_room_candidates,
        detect_linework_room_candidates,
    )
    from core.parser.dxf_parser import DxfParser
    from ui.main_window import MainWindow

    _ = QApplication.instance() or QApplication([])
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    dxf_path = str(tmp_path / "sample_02_multi_rect.dxf")
    with open(os.path.join(data_dir, "sample_02_multi_rect.dxf"), "rb") as src, open(
        dxf_path, "wb"
    ) as dst:
        dst.write(src.read())

    window = MainWindow()
    drawing = DxfParser().parse(dxf_path)
    window._on_load_finished(dxf_path, drawing)
    polyline = detect_closed_polyline_room_candidates(drawing)
    linework = detect_linework_room_candidates(drawing)
    window._on_room_detection_finished(polyline, linework)
    assert len(window._rooms) == 2

    # 1 件目の名前を編集し、2 件目を却下する。
    first, second = window._rooms
    window._room_panel.show_room(first)
    window._room_panel._name_edit.setText("会議室")
    window._room_panel._name_edit.editingFinished.emit()
    window._room_panel.show_room(second)
    window._room_panel._btn_reject.click()

    sidecar = tmp_path / "sample_02_multi_rect.rooms.json"
    assert sidecar.exists()
    saved = json.loads(sidecar.read_text(encoding="utf-8"))
    assert saved["rooms"][first.room_id]["room_name"] == "会議室"
    assert saved["rooms"][second.room_id]["review_status"] == "rejected"

    # 再検出すると、保存した内容が復元される。
    fresh = associate_room_names(
        drawing,
        deduplicate_room_candidates(
            detect_closed_polyline_room_candidates(drawing),
            detect_linework_room_candidates(drawing),
        ),
    )
    assert fresh[0].room_name != "会議室"
    window._on_room_detection_finished(polyline, linework)
    restored = {r.room_id: r for r in window._rooms}
    assert restored[first.room_id].room_name == "会議室"
    assert restored[second.room_id].review_status == REVIEW_STATUS_REJECTED
    window.close()
