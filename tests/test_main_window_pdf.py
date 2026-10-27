"""MainWindow の PDF 読み込み・寸法照合・倍率調整のテスト。"""
import os
import time

import pymupdf
import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PySide6.QtTest import QTest

from core.parser.dxf_parser import DxfParser
from core.drawing_viewer.dimension_overlay import DIMENSION_ITEM_ROLE
from tests.test_pdf_parser import _make_two_room_pdf
from ui.main_window import MainWindow
from ui.scale_dialog import PdfScaleDialog, SCALE_DIALOG_CANCELLED


def _ensure_qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _wait_for_load(window, timeout_s=10.0):
    """読み込みスレッドの終了を待つ。"""
    deadline = time.monotonic() + timeout_s
    while window._load_thread is not None and time.monotonic() < deadline:
        # QTest.qWait でのポーリングはワーカーの GIL を奪い、Windows CI で
        # 読み込みスレッドが進まなくなる（止まる・落ちる）ため、sleep で
        # GIL を譲りつつイベント処理で完了シグナルを受け取る。
        time.sleep(0.1)
        QApplication.processEvents()
    assert window._load_thread is None, "図面の読み込みが時間内に終わりませんでした"
    assert window._drawing is not None


def _wait_for_detection(window, timeout_s=10.0):
    """部屋検出スレッドの終了を待つ。"""
    deadline = time.monotonic() + timeout_s
    while window._room_thread is not None and time.monotonic() < deadline:
        # QTest.qWait でのポーリングはワーカーの GIL を奪うため sleep で待つ。
        time.sleep(0.1)
        QApplication.processEvents()
    assert window._room_thread is None, "部屋検出が時間内に終わりませんでした"


def _make_pdf(tmp_path, name="two_rooms.pdf"):
    pdf_path = os.path.join(tmp_path, name)
    _make_two_room_pdf(pdf_path)
    return pdf_path


def _make_matching_pdf(tmp_path):
    """寸法通りの部屋 1 つだけの PDF を作る。"""
    pdf_path = os.path.join(tmp_path, "matching.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=1200, height=900)
    page.draw_rect(pymupdf.Rect(100, 100, 500, 400), color=(0, 0, 0), fill=None, width=1)
    page.draw_line(pymupdf.Point(100, 450), pymupdf.Point(500, 450), color=(0, 0, 0), width=0.5)
    page.draw_line(pymupdf.Point(100, 400), pymupdf.Point(100, 460), color=(0, 0, 0), width=0.5)
    page.draw_line(pymupdf.Point(500, 400), pymupdf.Point(500, 460), color=(0, 0, 0), width=0.5)
    page.insert_text((280, 440), "4000", fontsize=12)
    doc.save(pdf_path)
    doc.close()
    return pdf_path


@pytest.fixture
def quiet_message_boxes(monkeypatch):
    """QMessageBox を出さず、呼び出しを記録する。"""
    calls = []

    def _info(*args, **kwargs):
        calls.append(("information", args[1] if len(args) > 1 else "", args[2] if len(args) > 2 else ""))
        return QMessageBox.StandardButton.Ok

    def _warning(*args, **kwargs):
        calls.append(("warning", args[1] if len(args) > 1 else "", args[2] if len(args) > 2 else ""))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", staticmethod(_info))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(_warning))
    return calls


def _open_pdf_with_scale(window, monkeypatch, pdf_path, scale):
    """ファイルダイアログと換算率ダイアログを迂回して PDF を開く。"""
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (pdf_path, "")),
    )
    monkeypatch.setattr(window, "_ask_pdf_scale", lambda path: scale)
    window._open_drawing()
    _wait_for_load(window)


def test_open_pdf_runs_dimension_check(tmp_path, monkeypatch, quiet_message_boxes):
    _ensure_qt_app()
    pdf_path = _make_pdf(tmp_path)
    window = MainWindow()
    _open_pdf_with_scale(window, monkeypatch, pdf_path, 10.0)

    assert window._drawing.file_type == "pdf"
    assert len(window._dimension_checks) == 2
    statuses = {c.dimension_text: c.status for c in window._dimension_checks}
    assert statuses == {"4000": "matched", "2000": "mismatched"}
    assert "寸法照合: 2 件" in window._log_text.toPlainText()
    # 寸法照合の印が 2 件表示され、倍率調整ボタンが有効になる。
    markers = [
        item for item in window._scene.items()
        if item.data(DIMENSION_ITEM_ROLE) is not None
    ]
    assert len(markers) == 2
    assert window._act_calibrate.isEnabled()
    window.close()


def test_open_pdf_without_scale_warns(tmp_path, monkeypatch, quiet_message_boxes):
    _ensure_qt_app()
    pdf_path = _make_pdf(tmp_path)
    window = MainWindow()
    _open_pdf_with_scale(window, monkeypatch, pdf_path, None)

    assert window._drawing._meta["units_source"] == "not_determined"
    assert "1pt=1mm" in window._log_text.toPlainText()
    # 換算率なし（1pt=1mm）でも照合は走る。実測 400mm に対して寸法 4000mm。
    assert len(window._dimension_checks) == 2
    assert all(c.status == "mismatched" for c in window._dimension_checks)
    window.close()


def test_open_pdf_scale_dialog_cancelled_does_not_load(
    tmp_path, monkeypatch, quiet_message_boxes
):
    _ensure_qt_app()
    pdf_path = _make_pdf(tmp_path)
    window = MainWindow()
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (pdf_path, "")),
    )
    monkeypatch.setattr(window, "_ask_pdf_scale", lambda path: SCALE_DIALOG_CANCELLED)
    window._open_drawing()

    assert window._drawing is None
    assert window._load_thread is None
    window.close()


def _make_three_room_pdf(tmp_path):
    """3 部屋の PDF。各部屋の寸法が同じ方向に 2% ずれている。

    4000/408pt、2000/204pt、3000/306pt はすべて同じ換算率 9.8039mm/pt を
    示すため、合意形成で倍率調整できる。
    """
    pdf_path = os.path.join(tmp_path, "three_rooms.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=1600, height=900)
    rooms = [
        (100, 508, "4000"),
        (600, 804, "2000"),
        (900, 1206, "3000"),
    ]
    for x0, x1, text in rooms:
        page.draw_rect(pymupdf.Rect(x0, 100, x1, 400), color=(0, 0, 0), fill=None, width=1)
        page.draw_line(pymupdf.Point(x0, 450), pymupdf.Point(x1, 450), color=(0, 0, 0), width=0.5)
        page.draw_line(pymupdf.Point(x0, 400), pymupdf.Point(x0, 460), color=(0, 0, 0), width=0.5)
        page.draw_line(pymupdf.Point(x1, 400), pymupdf.Point(x1, 460), color=(0, 0, 0), width=0.5)
        page.insert_text(((x0 + x1) / 2 - 20, 440), text, fontsize=12)
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def test_calibrate_scale_from_mismatched_dimension(
    tmp_path, monkeypatch, quiet_message_boxes
):
    _ensure_qt_app()
    pdf_path = _make_three_room_pdf(tmp_path)
    window = MainWindow()
    _open_pdf_with_scale(window, monkeypatch, pdf_path, 10.0)
    assert window._act_calibrate.isEnabled()

    window._calibrate_scale()
    _wait_for_detection(window)

    # 3 件の寸法が合意した換算率 2000/204 (= 4000/408 = 3000/306) を求め、
    # 図面を縮小する。
    assert window._drawing.scale == pytest.approx(2000.0 / 204.0)
    assert window._drawing._meta["units_source"] == "calibrated_from_dimension"
    assert "倍率調整" in window._log_text.toPlainText()
    # 調整後の再照合では、3 件の寸法がすべて一致している。
    rechecked = {c.dimension_text: c.status for c in window._dimension_checks}
    assert rechecked == {"4000": "matched", "2000": "matched", "3000": "matched"}
    # 部屋の検出もやり直されている。
    assert len(window._rooms) == 3
    window.close()


def test_calibrate_refuses_with_single_mismatched_dimension(
    tmp_path, monkeypatch, quiet_message_boxes
):
    # 不一致の寸法が 1 件だけでは、合意が取れないため調整しない。
    # 1 件だけの寸法から換算率を決めると、外れ値を信じて倍率を壊す。
    _ensure_qt_app()
    pdf_path = _make_pdf(tmp_path)
    window = MainWindow()
    _open_pdf_with_scale(window, monkeypatch, pdf_path, 10.0)
    assert window._act_calibrate.isEnabled()

    window._calibrate_scale()

    assert window._drawing.scale == pytest.approx(10.0)
    assert window._drawing._meta["units_source"] != "calibrated_from_dimension"
    assert "一致しません" in window._log_text.toPlainText()
    window.close()


def test_calibrate_with_no_mismatch_does_nothing(
    tmp_path, monkeypatch, quiet_message_boxes
):
    _ensure_qt_app()
    pdf_path = _make_matching_pdf(tmp_path)
    window = MainWindow()
    _open_pdf_with_scale(window, monkeypatch, pdf_path, 10.0)
    assert not window._act_calibrate.isEnabled()
    scale_before = window._drawing.scale

    window._calibrate_scale()

    assert window._drawing.scale == scale_before
    assert any("調整対象の寸法がありません" in text for _, _, text in quiet_message_boxes)
    assert "調整対象の寸法がないため" in window._log_text.toPlainText()
    window.close()


def test_dimension_overlay_toggle(tmp_path, monkeypatch, quiet_message_boxes):
    _ensure_qt_app()
    pdf_path = _make_pdf(tmp_path)
    window = MainWindow()
    _open_pdf_with_scale(window, monkeypatch, pdf_path, 10.0)

    def _markers():
        return [
            item for item in window._scene.items()
            if item.data(DIMENSION_ITEM_ROLE) is not None
        ]

    assert all(m.isVisible() for m in _markers())
    window._act_toggle_dimensions.setChecked(False)
    assert all(not m.isVisible() for m in _markers())
    window._act_toggle_dimensions.setChecked(True)
    assert all(m.isVisible() for m in _markers())
    window.close()


def test_click_dimension_marker_shows_details(
    tmp_path, monkeypatch, quiet_message_boxes
):
    _ensure_qt_app()
    pdf_path = _make_pdf(tmp_path)
    window = MainWindow()
    _open_pdf_with_scale(window, monkeypatch, pdf_path, 10.0)

    marker = next(
        item for item in window._scene.items()
        if item.data(DIMENSION_ITEM_ROLE) == "DIM002"
    )
    marker.setSelected(True)
    QTest.qWait(50)

    assert window._property_panel.title_label.text() == "寸法照合"
    table_texts = [
        window._property_panel.table.item(row, 1).text()
        for row in range(window._property_panel.table.rowCount())
    ]
    assert any("2000" in text for text in table_texts)
    assert any("不一致" in text for text in table_texts)
    window.close()


def test_dxf_load_has_no_dimension_overlay(monkeypatch, quiet_message_boxes):
    """DXF を開いても寸法照合は走らず、倍率調整ボタンは無効のまま。"""
    _ensure_qt_app()
    window = MainWindow()
    dxf_path = os.path.join(os.path.dirname(__file__), "..", "data", "sample_01_rect.dxf")
    drawing = DxfParser().parse(dxf_path)
    window._on_load_finished(dxf_path, drawing)

    assert window._drawing.file_type == "dxf"
    assert window._dimension_checks == []
    assert not window._act_calibrate.isEnabled()
    window.close()


def test_pdf_scale_dialog_parse():
    assert PdfScaleDialog.parse_scale_text("10") == (10.0, None)
    assert PdfScaleDialog.parse_scale_text("10.5") == (10.5, None)
    assert PdfScaleDialog.parse_scale_text("") == (None, None)
    assert PdfScaleDialog.parse_scale_text("   ") == (None, None)
    value, error = PdfScaleDialog.parse_scale_text("abc")
    assert value is None and error is not None
    value, error = PdfScaleDialog.parse_scale_text("0")
    assert value is None and error is not None
    value, error = PdfScaleDialog.parse_scale_text("-5")
    assert value is None and error is not None
