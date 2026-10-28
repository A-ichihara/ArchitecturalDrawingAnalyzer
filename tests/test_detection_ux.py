"""検出の進捗表示と部屋ラベルの重なり整理のテスト。"""
import os

import pytest
from PySide6.QtCore import Qt

from core.drawing_viewer.room_overlay import RoomOverlayRenderer
from core.drawing_viewer.scene import DrawingScene
from core.models.drawing import Drawing, LineElement
from core.models.room import Room


def _ensure_qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _room(room_id, name, x, y, w, h):
    return Room(
        room_id=room_id,
        room_name=name,
        area_m2=w * h / 1e6,
        boundary=[
            [x, y],
            [x + w, y],
            [x + w, y + h],
            [x, y + h],
        ],
    )


def _drawing_with_one_room():
    """1部屋分の線分だけを持つ図面（ワーカーの進捗テスト用）。"""
    elements = [
        LineElement(element_id="L1", element_type="LINE", layer="0",
                    start=[0, 0], end=[4000, 0]),
        LineElement(element_id="L2", element_type="LINE", layer="0",
                    start=[4000, 0], end=[4000, 3000]),
        LineElement(element_id="L3", element_type="LINE", layer="0",
                    start=[4000, 3000], end=[0, 3000]),
        LineElement(element_id="L4", element_type="LINE", layer="0",
                    start=[0, 3000], end=[0, 0]),
    ]
    return Drawing(
        drawing_id="ux-test", file_name="ux-test.dxf",
        file_type="dxf", units="mm", elements=elements,
    )


def test_worker_emits_progress_stages_in_order():
    """検出ワーカーが各段階の進捗メッセージを順に送る。"""
    _ensure_qt_app()
    from ui.main_window import RoomDetectionWorker

    worker = RoomDetectionWorker(_drawing_with_one_room())
    messages = []
    worker.progress.connect(messages.append)
    worker.run()
    assert messages == [
        "ポリラインの部屋候補を検出中…",
        "線分の部屋候補を検出中…",
        "二重線の壁ペアを検出中…",
        "壁ペア線分の部屋候補を検出中…",
    ]


def _close_view(view):
    """表示したビューを閉じ、遅延削除まで処理する。

    表示したままテストを終えると、ビューやシーンの破棄が後続の
    テストの実行中に行われ、Windows では後片付けの最中に
    アクセス違反で落ちることがあるため、明示的に片付ける。
    """
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    view.close()
    app = QApplication.instance()
    if app is not None:
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def _grid_rooms():
    """横一列に並んだ小部屋 10 件 + 大きな部屋 1 件。"""
    rooms = []
    for i in range(10):
        rooms.append(_room(f"R{i}", f"小部屋{i}", i * 3100, 0, 3000, 3000))
    rooms.append(_room("BIG", "大広間", 0, 4000, 9000, 9000))
    return rooms


def _visible_label_count(renderer):
    return sum(
        1 for label, _area in renderer._labels.values() if label.isVisible()
    )


def test_label_visibility_declutters_at_fit_zoom():
    """全体表示では重なるラベルが隠れ、大きい部屋のラベルが残る。"""
    _ensure_qt_app()
    from PySide6.QtWidgets import QGraphicsView

    scene = DrawingScene()
    renderer = RoomOverlayRenderer()
    rooms = _grid_rooms()
    renderer.render_rooms(rooms, scene)

    view = QGraphicsView(scene)
    # 幅 400px の狭いビューポートで全体表示する（実図面の
    # 全体表示と同じく、部屋の間隔よりラベル幅のほうが広い状態）。
    # show しないとビューポートが既定サイズのままになるため表示する。
    view.resize(400, 300)
    view.show()
    _ensure_qt_app().processEvents()
    view.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    renderer.update_label_visibility(view)
    visible = _visible_label_count(renderer)
    # 11 件のラベルがすべて表示されることはない（小部屋が横並びで重なる）。
    assert 0 < visible < len(rooms)
    # 最も大きい部屋のラベルは残る。
    big_label, _area = renderer._labels["BIG"]
    assert big_label.isVisible()
    _close_view(view)


def test_label_visibility_shows_more_when_zoomed_in():
    """ズームインすると隠れていたラベルが表示される。"""
    _ensure_qt_app()
    from PySide6.QtWidgets import QGraphicsView

    scene = DrawingScene()
    renderer = RoomOverlayRenderer()
    renderer.render_rooms(_grid_rooms(), scene)

    view = QGraphicsView(scene)
    view.resize(400, 300)
    view.show()
    _ensure_qt_app().processEvents()
    view.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
    renderer.update_label_visibility(view)
    visible_fit = _visible_label_count(renderer)

    view.scale(4.0, 4.0)
    renderer.update_label_visibility(view)
    visible_zoomed = _visible_label_count(renderer)

    assert visible_zoomed > visible_fit
    _close_view(view)


def test_label_visibility_with_no_labels_does_nothing():
    """ラベルがない状態でもビューがなくても落ちない。"""
    _ensure_qt_app()
    renderer = RoomOverlayRenderer()
    renderer.update_label_visibility(None)
