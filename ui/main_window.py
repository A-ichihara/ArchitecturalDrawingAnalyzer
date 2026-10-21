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

from core.drawing_viewer.scene import DrawingScene
from core.drawing_viewer.view import DrawingView
from core.drawing_viewer.renderers import DxfRenderer
from core.parser.dxf_parser import DxfParser
from core.models.drawing import Drawing, DrawingElement
from core.analyzer.drawing_analyzer import DrawingAnalyzer
from core.analyzer.room_detector import (
    detect_closed_polyline_room_candidates,
    detect_linework_room_candidates,
)

from ui.panels.layer_panel import LayerPanel
from ui.panels.property_panel import PropertyPanel
from ui.panels.element_tree import ElementTreePanel

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
        self._load_thread: Optional[QThread] = None
        self._worker: Optional[DxfLoadWorker] = None

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

        # 右ドック (プロパティ)
        self._right_dock = QDockWidget("要素プロパティ", self)
        self._right_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        
        self._property_panel = PropertyPanel()
        self._right_dock.setWidget(self._property_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._right_dock)

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
        if self._load_thread is not None and self._load_thread.isRunning():
            self._log("warn", "別のDXFを読み込み中のため、新しい読み込みを開始しませんでした。")
            return

        self._act_open.setEnabled(False)
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
        self._act_detect_rooms.setEnabled(True)

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
        """現在のDXFから暫定的な閉領域候補を抽出して一覧表示する。"""
        if self._drawing is None:
            return
        try:
            polyline_rooms = detect_closed_polyline_room_candidates(self._drawing)
            linework_rooms = detect_linework_room_candidates(self._drawing)
        except ValueError as exc:
            QMessageBox.warning(self, "部屋候補の検出", str(exc))
            return
        rooms = polyline_rooms + linework_rooms
        self._log("info", f"部屋候補: ポリライン {len(polyline_rooms)} 件 / 線分 {len(linework_rooms)} 件")
        if not rooms:
            QMessageBox.information(self, "部屋候補の検出", "閉じた領域候補は見つかりませんでした。")
            return
        lines = [f"{index}. {room.area_m2:.2f} ㎡（{room.properties[\'candidate_type\']}）"
                 for index, room in enumerate(rooms, start=1)]
        preview = "\\n".join(lines[:30])
        if len(lines) > 30:
            preview += f"\\n…ほか {len(lines) - 30} 件"
        QMessageBox.information(
            self, "部屋候補の検出",
            f"暫定的な閉領域候補: {len(rooms)} 件\\n"
            "※ 部屋名・壁芯は未判定です。重複候補が含まれる場合があります。\\n\\n"
            + preview,
        )

    def _fit_view(self) -> None:
        """全体表示を実行する。"""
        self._view.fit_in_view()

    def _on_zoom_changed(self, zoom: float) -> None:
        """ズーム倍率変更時にステータスバーを更新する。"""
        self._label_zoom.setText(f"ズーム：{zoom * 100:.1f}%")

    def _on_mouse_world_pos_changed(self, x: float, y: float) -> None:
        """マウス移動時にワールド座標表示を更新する。"""
        self._label_coords.setText(f"座標：({x:.2f}, {y:.2f}) mm")

    def _on_layer_visibility_changed(self, layer_name: str, visible: bool) -> None:
        """レイヤーパネルで表示トグルが変更されたときの処理。"""
        self._renderer.set_layer_visible(layer_name, visible)

    def _on_scene_selection_changed(self) -> None:
        """ビュー上で要素の選択状態が変更されたときの処理。"""
        selected_items = self._scene.selectedItems()
        if not selected_items or self._drawing is None:
            self._property_panel.clear()
            return

        item = selected_items[0]
        element_id = item.data(Qt.ItemDataRole.UserRole)
        if element_id:
            elem = self._drawing.get_element_by_id(element_id)
            self._property_panel.show_element(elem)

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
