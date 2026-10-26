"""
ui.main_window
建築図面解析・設備設計支援システムのメインウィンドウ。
ツールバー、Drawing Viewer、ステータスバーで構成されます。
"""

import html
import logging
import os
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QToolBar, QStatusBar, QFileDialog, QMessageBox,
    QLabel, QSizePolicy, QDockWidget, QTextEdit, QPushButton,
    QTabWidget
)
from PySide6.QtCore import Qt, QThread, Signal, QObject, Slot
from PySide6.QtGui import QAction, QIcon, QKeySequence, QColor

from core.drawing_viewer.scene import DrawingScene, DrawingLayer
from core.drawing_viewer.view import DrawingView
from core.drawing_viewer.renderers import DxfRenderer
from core.drawing_viewer.room_overlay import ROOM_ITEM_ROLE, RoomOverlayRenderer
from core.export.room_export import export_rooms
from core.parser.dxf_parser import DxfParser
from core.models.drawing import Drawing, DrawingElement
from core.models.room import Room
from core.analyzer.drawing_analyzer import DrawingAnalyzer
from core.analyzer.room_detector import (
    associate_room_names,
    detect_closed_polyline_room_candidates,
    detect_linework_room_candidates,
    deduplicate_room_candidates,
)
from core.analyzer.wall_detector import (
    area_factor_for_units,
    attach_wall_info,
    detect_wall_pairs,
)

from ui.panels.layer_panel import LayerPanel
from ui.panels.property_panel import PropertyPanel
from ui.panels.element_tree import ElementTreePanel
from ui.panels.room_panel import RoomPanel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# バックグラウンドDXF読み込みワーカー
# ---------------------------------------------------------------------------

class DxfLoadWorker(QObject):
    """DXFファイルをバックグラウンドスレッドで読み込むワーカー。"""
    finished = Signal(str, object)  # ファイルパス、Drawing オブジェクト
    error = Signal(str, str)       # ファイルパス、エラーメッセージ

    def __init__(self, file_path: str):
        super().__init__()
        self._file_path = file_path

    def run(self) -> None:
        try:
            parser = DxfParser()
            drawing = parser.parse(self._file_path)
            self.finished.emit(self._file_path, drawing)
        except Exception as e:
            self.error.emit(self._file_path, str(e))


class RoomDetectionWorker(QObject):
    """部屋候補の検出をGUIスレッドの外で実行する。"""

    finished = Signal(object, object)
    error = Signal(str)

    def __init__(self, drawing: Drawing):
        super().__init__()
        self._drawing = drawing

    @Slot()
    def run(self) -> None:
        try:
            polyline_rooms = detect_closed_polyline_room_candidates(self._drawing)
            linework_rooms = detect_linework_room_candidates(self._drawing)
            self.finished.emit(polyline_rooms, linework_rooms)
        except Exception as exc:
            logger.exception("部屋候補の検出に失敗しました")
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# メインウィンドウ
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """
    建築図面解析・設備設計支援システム メインウィンドウ。
    
    構成:
        - ツールバー: [DXFを開く] [全体表示] [ズームイン] [ズームアウト]
        - 左ドック: [レイヤー一覧] / [要素ツリー] タブ
        - 中央: DrawingView（DXF図面表示エリア）
        - 右ドック: [プロパティ]
        - 下部ステータスバー: ファイル名・状態・座標・要素数・ズーム率
        - 下部ドック: ログ表示エリア
    """

    APP_TITLE = "建築図面解析・設備設計支援システム"
    VERSION = "Phase 2"

    def __init__(self):
        super().__init__()
        self._current_file: Optional[str] = None
        self._drawing: Optional[Drawing] = None
        self._rooms: list[Room] = []
        self._area_basis: str = "inner"
        self._room_overlay = RoomOverlayRenderer()
        self._load_thread: Optional[QThread] = None
        self._worker: Optional[DxfLoadWorker] = None
        self._room_thread: Optional[QThread] = None
        self._room_worker: Optional[RoomDetectionWorker] = None

        self._setup_ui()
        self._setup_logging()
        self._update_title()

    # ------------------------------------------------------------------
    # UI構築
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle(self.APP_TITLE)
        self.resize(1400, 850)
        self._apply_stylesheet()

        # シーン＋ビュー
        self._scene = DrawingScene()
        self._view = DrawingView(self._scene, self)
        self._renderer = DxfRenderer()

        # ツールバー
        self._setup_toolbar()

        # 中央ウィジェット
        self.setCentralWidget(self._view)

        # ドックパネル（3ペイン構成）
        self._setup_side_docks()

        # ステータスバー
        self._setup_statusbar()

        # ログドック
        self._setup_log_dock()

        # シグナル接続
        self._view.zoom_changed.connect(self._on_zoom_changed)
        self._view.mouse_world_pos_changed.connect(self._on_mouse_world_pos_changed)
        self._scene.selectionChanged.connect(self._on_scene_selection_changed)

        self._layer_panel.layer_visibility_changed.connect(self._on_layer_visibility_changed)
        self._element_tree_panel.element_selected.connect(self._on_tree_element_selected)

    def _setup_toolbar(self) -> None:
        toolbar = QToolBar("メインツールバー", self)
        toolbar.setMovable(False)
        toolbar.setStyleSheet("QToolBar { spacing: 6px; padding: 4px; }")
        self.addToolBar(toolbar)

        # DXFを開く
        self._act_open = QAction("📂 DXFを開く", self)
        self._act_open.setShortcut(QKeySequence.StandardKey.Open)
        self._act_open.setStatusTip("DXFファイルを開いて図面を表示します")
        self._act_open.triggered.connect(self._open_dxf)
        toolbar.addAction(self._act_open)

        self._act_detect_rooms = QAction("部屋候補を検出", self)
        self._act_detect_rooms.setEnabled(False)
        self._act_detect_rooms.setStatusTip("閉じたポリライン・接続線分から仮の部屋領域を抽出します")
        self._act_detect_rooms.triggered.connect(self._detect_room_candidates)
        toolbar.addAction(self._act_detect_rooms)

        self._act_export_rooms = QAction("💾 部屋一覧を出力", self)
        self._act_export_rooms.setEnabled(False)
        self._act_export_rooms.setStatusTip("確認した部屋一覧を CSV / Excel で保存します")
        self._act_export_rooms.triggered.connect(self._export_rooms)
        toolbar.addAction(self._act_export_rooms)

        toolbar.addSeparator()

        # 全体表示
        act_fit = QAction("🔭 全体表示", self)
        act_fit.setShortcut("F")
        act_fit.setStatusTip("図面全体が画面に収まるよう表示します")
        act_fit.triggered.connect(self._fit_view)
        toolbar.addAction(act_fit)

        # ズームイン
        act_zoom_in = QAction("🔍＋", self)
        act_zoom_in.setShortcut(QKeySequence.StandardKey.ZoomIn)
        act_zoom_in.setStatusTip("ズームイン")
        act_zoom_in.triggered.connect(self._view.zoom_in)
        toolbar.addAction(act_zoom_in)

        # ズームアウト
        act_zoom_out = QAction("🔍－", self)
        act_zoom_out.setShortcut(QKeySequence.StandardKey.ZoomOut)
        act_zoom_out.setStatusTip("ズームアウト")
        act_zoom_out.triggered.connect(self._view.zoom_out)
        toolbar.addAction(act_zoom_out)

    def _setup_side_docks(self) -> None:
        """左右のサイドドックパネルを初期化構築する。"""
        # 左ドック (レイヤー + 要素ツリー)
        self._left_dock = QDockWidget("構造解析", self)
        self._left_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        
        tab_left = QTabWidget()
        self._layer_panel = LayerPanel()
        self._element_tree_panel = ElementTreePanel()

        tab_left.addTab(self._layer_panel, "レイヤー")
        tab_left.addTab(self._element_tree_panel, "要素ツリー")
        self._left_dock.setWidget(tab_left)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._left_dock)

        # 右ドック (プロパティ + 部屋一覧)
        self._right_dock = QDockWidget("要素プロパティ", self)
        self._right_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)

        tab_right = QTabWidget()
        self._property_panel = PropertyPanel()
        self._room_panel = RoomPanel()
        tab_right.addTab(self._property_panel, "要素プロパティ")
        tab_right.addTab(self._room_panel, "部屋一覧")
        self._right_tabs = tab_right
        self._right_dock.setWidget(tab_right)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._right_dock)

        # 部屋パネルのシグナル接続
        self._room_panel.room_selected.connect(self._on_room_panel_selected)
        self._room_panel.room_name_changed.connect(self._on_room_name_changed)
        self._room_panel.room_status_changed.connect(self._on_room_status_changed)
        self._room_panel.area_basis_changed.connect(self._on_area_basis_changed)

    def _setup_statusbar(self) -> None:
        statusbar = QStatusBar()
        self.setStatusBar(statusbar)

        self._label_file = QLabel("ファイル：（未選択）")
        self._label_status = QLabel("状態：待機中")
        self._label_coords = QLabel("座標：(0.00, 0.00) mm")
        self._label_elements = QLabel("")
        self._label_zoom = QLabel("ズーム：100%")

        statusbar.addWidget(self._label_file, 2)
        statusbar.addWidget(self._label_status, 2)
        statusbar.addWidget(self._label_coords, 2)
        statusbar.addWidget(self._label_elements, 1)
        statusbar.addPermanentWidget(self._label_zoom)

    def _setup_log_dock(self) -> None:
        dock = QDockWidget("ログ", self)
        dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(150)
        self._log_text.setStyleSheet(
            "QTextEdit { background: #13131f; color: #a9b1d6; font-family: monospace; font-size: 12px; }"
        )
        dock.setWidget(self._log_text)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

    def _apply_stylesheet(self) -> None:
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1a1b2e;
            }
            QToolBar {
                background-color: #16213e;
                border-bottom: 1px solid #0f3460;
                color: #e0e0e0;
                font-size: 14px;
            }
            QToolButton {
                background: transparent;
                border: none;
                color: #a9b1d6;
                padding: 4px 10px;
                border-radius: 4px;
                font-size: 13px;
            }
            QToolButton:hover {
                background-color: #0f3460;
                color: #7dcfff;
            }
            QToolButton:pressed {
                background-color: #1a4a80;
            }
            QStatusBar {
                background-color: #16213e;
                color: #a9b1d6;
                font-size: 12px;
                border-top: 1px solid #0f3460;
            }
            QDockWidget {
                color: #a9b1d6;
            }
            QDockWidget::title {
                background: #16213e;
                padding: 4px;
                font-weight: bold;
            }
            QTabWidget::pane {
                border: 1px solid #0f3460;
            }
            QTabBar::tab {
                background: #16213e;
                color: #a9b1d6;
                padding: 6px 12px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background: #1a1b2e;
                color: #7aa2f7;
                font-weight: bold;
            }
        """)

    # ------------------------------------------------------------------
    # スロット
    # ------------------------------------------------------------------

    def _open_dxf(self) -> None:
        """DXFファイル選択ダイアログを開く。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "DXFファイルを開く",
            "",
            "DXF Files (*.dxf *.DXF);;All Files (*)",
        )
        if not file_path:
            return

        self._load_dxf(file_path)

    def _load_dxf(self, file_path: str) -> None:
        """DXFファイルをバックグラウンドで読み込む。

        同時に複数の読み込みスレッドを起動しないようにし、
        完了後にスレッドとワーカーの参照を安全に解放する。
        """
        if self._room_thread is not None and self._room_thread.isRunning():
            self._log("warn", "部屋候補の解析中は別のDXFを開けません。")
            return
        if self._load_thread is not None and self._load_thread.isRunning():
            self._log("warn", "別のDXFを読み込み中のため、新しい読み込みを開始しませんでした。")
            return

        self._act_open.setEnabled(False)
        self._act_detect_rooms.setEnabled(False)
        filename = os.path.basename(file_path)
        self._label_file.setText(f"ファイル：{filename}")
        self._label_status.setText("状態：読み込み中...")
        self._log("info", f"DXF読み込み開始: {file_path}")

        # バックグラウンドスレッドで読み込み
        self._load_thread = QThread(self)
        self._worker = DxfLoadWorker(file_path)
        self._worker.moveToThread(self._load_thread)
        self._load_thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_load_finished)
        self._worker.error.connect(self._on_load_error)
        self._worker.finished.connect(self._load_thread.quit)
        self._worker.error.connect(self._load_thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.error.connect(self._worker.deleteLater)
        self._load_thread.finished.connect(self._on_load_thread_finished)
        self._load_thread.finished.connect(self._load_thread.deleteLater)
        self._load_thread.start()

    @Slot()
    def _on_load_thread_finished(self) -> None:
        """読み込みスレッド終了後に参照を解放し、次の読み込みを許可する。"""
        self._worker = None
        self._load_thread = None
        self._act_open.setEnabled(True)
        self._act_detect_rooms.setEnabled(self._drawing is not None)

    def _on_load_finished(self, file_path: str, drawing: Drawing) -> None:
        """DXF読み込み完了時の処理。"""
        load_error = getattr(drawing, "_meta", {}).get("load_error")
        if load_error:
            self._on_load_error(file_path, load_error)
            return

        # 読み込みに成功した場合に限り、現在の図面ファイルとして確定する。
        self._current_file = file_path
        self._update_title()
        self._drawing = drawing
        self._rooms = []
        self._area_basis = "inner"
        self._room_overlay.clear(self._scene)
        self._room_panel.clear()
        self._room_panel.set_area_basis("inner")
        self._act_export_rooms.setEnabled(False)
        self._act_detect_rooms.setEnabled(True)
        self._label_coords.setText(
            f"座標：(0.00, 0.00) {self._coordinate_unit_suffix()}"
        )

        # レンダリング
        self._renderer.render(drawing, self._scene)

        # 構造解析
        stats = DrawingAnalyzer.analyze(drawing)

        # パネルの更新
        layer_info = getattr(drawing, "_meta", {}).get("layers", {})
        self._layer_panel.set_layers(stats.layers, layer_info=layer_info)
        for layer_name, info in layer_info.items():
            if not info["is_on"]:
                self._renderer.set_layer_visible(layer_name, False)
        self._element_tree_panel.set_drawing(drawing)
        self._property_panel.clear()

        # ビューを図面全体に合わせる
        self._fit_view()

        # ステータス更新
        self._label_status.setText("状態：表示完了")
        self._label_elements.setText(f"要素数：{stats.total_elements}")

        meta = getattr(drawing, "_meta", {})
        dxf_ver = meta.get("dxf_version", "不明")
        unsupported = meta.get("unsupported_types", {})

        self._log("info", f"読み込み完了: {stats.total_elements} 要素 / レイヤー数: {stats.layer_count} / DXFバージョン: {dxf_ver}")
        self._log("info", f"要素内訳: {stats.by_type}")
        if unsupported:
            self._log("warn", f"未対応エンティティ（スキップ）: {unsupported}")
        units_warning = meta.get("units_warning")
        if units_warning:
            self._log("warn", units_warning)

    def _on_load_error(self, file_path: str, message: str) -> None:
        """DXF読み込みエラー時の処理。"""
        self._label_status.setText("状態：読み込みエラー")
        # 読み込みに失敗したファイルを、現在表示中の図面として表示しない。
        current_name = os.path.basename(self._current_file) if self._current_file else "（未選択）"
        self._label_file.setText(f"ファイル：{current_name}")
        self._update_title()
        self._log("error", f"読み込みエラー: {message}")

        QMessageBox.warning(
            self,
            "DXF読み込みエラー",
            f"DXFファイルを読み込めませんでした。\n\n"
            f"原因：\nこのDXF形式は現在対応していない可能性があります。\n\n"
            f"詳細：\n{message}",
        )

    def _detect_room_candidates(self) -> None:
        """GUIをブロックせずに暫定的な部屋候補を検出する。"""
        if self._drawing is None or self._room_thread is not None:
            return
        self._act_detect_rooms.setEnabled(False)
        self._act_open.setEnabled(False)
        self._label_status.setText("状態：部屋候補を解析中...")
        self._room_thread = QThread(self)
        self._room_worker = RoomDetectionWorker(self._drawing)
        self._room_worker.moveToThread(self._room_thread)
        self._room_thread.started.connect(self._room_worker.run)
        self._room_worker.finished.connect(self._on_room_detection_finished)
        self._room_worker.error.connect(self._on_room_detection_error)
        self._room_worker.finished.connect(self._room_thread.quit)
        self._room_worker.error.connect(self._room_thread.quit)
        self._room_worker.finished.connect(self._room_worker.deleteLater)
        self._room_worker.error.connect(self._room_worker.deleteLater)
        self._room_thread.finished.connect(self._on_room_thread_finished)
        self._room_thread.finished.connect(self._room_thread.deleteLater)
        self._room_thread.start()

    @Slot()
    def _on_room_thread_finished(self) -> None:
        self._room_worker = None
        self._room_thread = None
        self._act_detect_rooms.setEnabled(self._drawing is not None)
        self._act_open.setEnabled(True)

    @Slot(str)
    def _on_room_detection_error(self, message: str) -> None:
        self._label_status.setText("状態：部屋候補の解析失敗")
        self._log("error", f"部屋候補の検出に失敗: {message}")
        QMessageBox.warning(self, "部屋候補の検出", f"解析に失敗しました。\n{message}")

    @Slot(object, object)
    def _on_room_detection_finished(self, polyline_rooms: list, linework_rooms: list) -> None:
        self._label_status.setText("状態：部屋候補の解析完了")
        rooms = deduplicate_room_candidates(polyline_rooms, linework_rooms)
        if self._drawing is not None:
            rooms = associate_room_names(self._drawing, rooms)
        self._rooms = rooms
        # 二重線の壁を検出し、壁芯面積が求まる部屋へ付与する。
        # 壁の検出に失敗しても部屋候補の表示は妨げない。
        if self._drawing is not None:
            try:
                wall_pairs = detect_wall_pairs(self._drawing)
                factor = area_factor_for_units(self._drawing.units)
                attached = attach_wall_info(rooms, wall_pairs, factor)
                self._log(
                    "info",
                    f"二重線の壁: {len(wall_pairs)} 組 / 壁芯面積を算出できた部屋: {attached} 件",
                )
            except Exception as exc:
                logger.exception("二重線の壁の検出に失敗しました")
                self._log("warn", f"二重線の壁の検出に失敗しました: {exc}")
        self._log("info", f"部屋候補: ポリライン {len(polyline_rooms)} 件 / 線分 {len(linework_rooms)} 件")
        if not rooms:
            self._room_overlay.clear(self._scene)
            self._room_panel.clear()
            self._act_export_rooms.setEnabled(False)
            QMessageBox.information(self, "部屋候補の検出", "閉じた領域候補は見つかりませんでした。")
            return
        # 図面上に部屋候補を重ねて表示し、部屋一覧パネルに反映する。
        self._room_overlay.clear(self._scene)
        self._room_overlay.render_rooms(rooms, self._scene, self._area_basis)
        self._room_panel.set_rooms(rooms)
        self._room_panel.set_area_basis(self._area_basis)
        self._area_basis = self._room_panel.area_basis
        self._act_export_rooms.setEnabled(True)
        self._label_status.setText(f"状態：部屋候補 {len(rooms)} 件を検出")
        self._log("info", f"部屋候補 {len(rooms)} 件を図面に表示しました。部屋をクリックして名前や状態を確認できます。")

    def _fit_view(self) -> None:
        """全体表示を実行する。"""
        self._view.fit_in_view()

    def _on_zoom_changed(self, zoom: float) -> None:
        """ズーム倍率変更時にステータスバーを更新する。"""
        self._label_zoom.setText(f"ズーム：{zoom * 100:.1f}%")

    def _coordinate_unit_suffix(self) -> str:
        """現在の図面座標に対応する単位表示を返す。"""
        units = (self._drawing.units if self._drawing is not None else "mm") or "mm"
        normalized = str(units).strip().lower()
        aliases = {
            "millimeter": "mm", "millimeters": "mm",
            "centimeter": "cm", "centimeters": "cm",
            "meter": "m", "meters": "m",
            "inch": "in", "inches": "in",
            "foot": "ft", "feet": "ft",
        }
        return aliases.get(normalized, normalized)

    def _on_mouse_world_pos_changed(self, x: float, y: float) -> None:
        """マウス移動時にワールド座標表示を更新する。"""
        self._label_coords.setText(
            f"座標：({x:.2f}, {y:.2f}) {self._coordinate_unit_suffix()}"
        )

    def _on_layer_visibility_changed(self, layer_name: str, visible: bool) -> None:
        """レイヤーパネルで表示トグルが変更されたときの処理。"""
        self._renderer.set_layer_visible(layer_name, visible)

    def _on_scene_selection_changed(self) -> None:
        """ビュー上で要素の選択状態が変更されたときの処理。"""
        selected_items = self._scene.selectedItems()
        if not selected_items:
            self._property_panel.clear()
            return

        item = selected_items[0]
        room_id = item.data(ROOM_ITEM_ROLE)
        if room_id:
            room = next((r for r in self._rooms if r.room_id == room_id), None)
            if room is not None:
                self._room_panel.select_room(room_id)
                self._room_panel.show_room(room)
                self._right_tabs.setCurrentWidget(self._room_panel)
                return
        if self._drawing is None:
            self._property_panel.clear()
            return
        element_id = item.data(Qt.ItemDataRole.UserRole)
        if element_id:
            elem = self._drawing.get_element_by_id(element_id)
            self._property_panel.show_element(elem)
            self._right_tabs.setCurrentWidget(self._property_panel)

    def _on_room_panel_selected(self, room_id: str) -> None:
        """部屋一覧パネルで部屋が選ばれたら、図面上の該当オーバーレイを選択する。"""
        self._scene.clearSelection()
        for item in self._scene.items():
            if item.data(ROOM_ITEM_ROLE) == room_id:
                item.setSelected(True)
                break

    def _on_room_name_changed(self, room_id: str, _new_name: str) -> None:
        """部屋名の編集をオーバーレイへ反映する。"""
        self._rerender_room_overlay()

    def _on_room_status_changed(self, room_id: str, _new_status: str) -> None:
        """確認状態の変更をオーバーレイへ反映する。"""
        self._rerender_room_overlay()

    def _on_area_basis_changed(self, basis: str) -> None:
        """面積基準の切り替えをオーバーレイと一覧へ反映する。"""
        self._area_basis = basis
        self._rerender_room_overlay()
        label = "壁芯" if basis == "centerline" else "内法"
        self._log("info", f"面積基準を「{label}」に切り替えました。")

    def _rerender_room_overlay(self) -> None:
        """現在の部屋一覧でオーバーレイを描き直す。"""
        self._room_overlay.clear(self._scene)
        if self._rooms:
            self._room_overlay.render_rooms(self._rooms, self._scene, self._area_basis)

    def _export_rooms(self) -> None:
        """確認した部屋一覧を CSV / Excel で保存する。"""
        if not self._rooms or self._drawing is None:
            return
        default_name = os.path.splitext(os.path.basename(self._current_file or "rooms"))[0]
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "部屋一覧を保存",
            f"{default_name}_rooms.csv",
            "CSV ファイル (*.csv);;Excel ファイル (*.xlsx)",
        )
        if not file_path:
            return
        try:
            export_rooms(
                self._rooms,
                file_path,
                drawing_name=os.path.basename(self._current_file or ""),
                units=self._drawing.units,
                area_basis=self._area_basis,
            )
        except Exception as exc:
            logger.exception("部屋一覧の出力に失敗しました")
            self._log("error", f"部屋一覧の出力に失敗: {exc}")
            QMessageBox.warning(self, "部屋一覧の出力", f"保存に失敗しました。\n{exc}")
            return
        self._log("info", f"部屋一覧を保存しました: {file_path}（{len(self._rooms)} 件）")
        self._label_status.setText("状態：部屋一覧を保存しました")

    def _on_tree_element_selected(self, element_id: str) -> None:
        """ツリーパネルで要素が選択されたときの処理。"""
        if self._drawing is None:
            return

        elem = self._drawing.get_element_by_id(element_id)
        self._property_panel.show_element(elem)

        # シーン上の該当アイテムを選択状態にする
        self._scene.clearSelection()
        for item in self._scene.items():
            if item.data(Qt.ItemDataRole.UserRole) == element_id:
                item.setSelected(True)
                break

    # ------------------------------------------------------------------
    # ロギング
    # ------------------------------------------------------------------

    def _setup_logging(self) -> None:
        """アプリログをログドックへも出力するハンドラーを設定する。"""
        handler = _QtLogHandler(self._log_text)
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
        handler.setFormatter(formatter)
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.DEBUG)

    def _log(self, level: str, message: str) -> None:
        """ログドックにメッセージを表示する（直接呼び出し用）。"""
        color_map = {"info": "#a9b1d6", "warn": "#e0af68", "error": "#f7768e"}
        color = color_map.get(level, "#a9b1d6")
        self._log_text.append(
            f'<span style="color:{color};">[{level.upper()}] {message}</span>'
        )

    def _update_title(self) -> None:
        filename = os.path.basename(self._current_file) if self._current_file else ""
        title = f"{self.APP_TITLE} - {self.VERSION}"
        if filename:
            title += f" | {filename}"
        self.setWindowTitle(title)



# ---------------------------------------------------------------------------
# GUIスレッドへの安全なログ受け渡し
# ---------------------------------------------------------------------------

class _QtLogBridge(QObject):
    """別スレッドからのログをGUIスレッドへ転送するブリッジ。"""

    message = Signal(str, str)  # color, escaped HTML message

    def __init__(self, widget: QTextEdit):
        super().__init__(widget)
        self._widget = widget
        self.message.connect(self._append_message, Qt.ConnectionType.QueuedConnection)

    @Slot(str, str)
    def _append_message(self, color: str, message: str) -> None:
        self._widget.append(f'<span style="color:{color};">{message}</span>')


class _QtLogHandler(logging.Handler):
    """PythonのloggingメッセージをGUIスレッド経由で QTextEdit に出力する。"""

    COLOR_MAP = {
        logging.DEBUG:    "#565f89",
        logging.INFO:     "#a9b1d6",
        logging.WARNING:  "#e0af68",
        logging.ERROR:    "#f7768e",
        logging.CRITICAL: "#ff007c",
    }

    def __init__(self, widget: QTextEdit):
        super().__init__()
        self._bridge = _QtLogBridge(widget)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = html.escape(self.format(record))
            color = self.COLOR_MAP.get(record.levelno, "#a9b1d6")
            self._bridge.message.emit(color, message)
        except Exception:
            self.handleError(record)
