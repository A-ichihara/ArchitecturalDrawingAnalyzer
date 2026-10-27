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
    QTabWidget, QComboBox, QDialog
)
from PySide6.QtCore import Qt, QThread, Signal, QObject, Slot
from PySide6.QtGui import QAction, QIcon, QKeySequence, QColor

from core.drawing_viewer.scene import DrawingScene, DrawingLayer
from core.drawing_viewer.view import DrawingView
from core.drawing_viewer.renderers import DxfRenderer
from core.drawing_viewer.room_overlay import ROOM_ITEM_ROLE, RoomOverlayRenderer
from core.drawing_viewer.dimension_overlay import (
    DIMENSION_ITEM_ROLE,
    DimensionOverlayRenderer,
)
from core.analyzer.dimension_check import (
    DimensionCheck,
    calibrate_scale_from_dimension,
    check_dimensions,
    rescale_drawing,
)
from core.export.room_export import export_rooms
from core.rooms.review_store import apply_reviews, load_reviews, save_reviews
from core.parser.dxf_parser import DxfParser
from core.parser.pdf_parser import PdfParser
from ui.scale_dialog import PdfScaleDialog, SCALE_DIALOG_CANCELLED
from core.models.drawing import Drawing, DrawingElement
from core.models.room import Room
from core.analyzer.drawing_analyzer import DrawingAnalyzer
from core.analyzer.room_detector import (
    associate_room_names,
    detect_closed_polyline_room_candidates,
    detect_linework_room_candidates,
    detect_wall_pair_room_candidates,
    deduplicate_room_candidates,
    merge_room_candidates,
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
# バックグラウンド図面読み込みワーカー
# ---------------------------------------------------------------------------

class DrawingLoadWorker(QObject):
    """図面ファイル（DXF / PDF）をバックグラウンドスレッドで読み込むワーカー。

    拡張子でパーサーを切り替える。PDF の場合は mm/pt 換算率を受け取り、
    未指定（None）の場合は 1pt=1mm として読み込む。
    """
    finished = Signal(str, object)  # ファイルパス、Drawing オブジェクト
    error = Signal(str, str)       # ファイルパス、エラーメッセージ

    def __init__(self, file_path: str, mm_per_pt: Optional[float] = None):
        super().__init__()
        self._file_path = file_path
        self._mm_per_pt = mm_per_pt

    def run(self) -> None:
        try:
            ext = os.path.splitext(self._file_path)[1].lower()
            if ext == ".pdf":
                drawing = PdfParser().parse(
                    self._file_path, scale_mm_per_pt=self._mm_per_pt
                )
            elif ext == ".dxf":
                drawing = DxfParser().parse(self._file_path)
            else:
                raise ValueError(f"対応していない図面形式です: {ext}")
            self.finished.emit(self._file_path, drawing)
        except Exception as e:
            self.error.emit(self._file_path, str(e))


class RoomDetectionWorker(QObject):
    """部屋候補の検出をGUIスレッドの外で実行する。"""

    finished = Signal(object, object, object, object)
    error = Signal(str)
    progress = Signal(str)

    def __init__(self, drawing: Drawing):
        super().__init__()
        self._drawing = drawing

    @Slot()
    def run(self) -> None:
        try:
            self.progress.emit("ポリラインの部屋候補を検出中…")
            polyline_rooms = detect_closed_polyline_room_candidates(self._drawing)
            self.progress.emit("線分の部屋候補を検出中…")
            linework_rooms = detect_linework_room_candidates(self._drawing)
        except Exception as exc:
            logger.exception("部屋候補の検出に失敗しました")
            self.error.emit(str(exc))
            return
        # 壁ペアの検出は部屋候補の表示を妨げない。失敗しても壁ペア部屋と
        # 壁芯面積の付与だけを諦め、全線分の部屋候補はそのまま表示する。
        wall_pair_rooms: list = []
        wall_pairs: list = []
        try:
            self.progress.emit("二重線の壁ペアを検出中…")
            wall_pairs = detect_wall_pairs(self._drawing)
            self.progress.emit("壁ペア線分の部屋候補を検出中…")
            wall_pair_rooms = detect_wall_pair_room_candidates(
                self._drawing, wall_pairs
            )
        except Exception:
            logger.exception("壁ペア部屋候補の検出に失敗しました")
            wall_pair_rooms = []
            wall_pairs = []
        self.finished.emit(
            polyline_rooms, linework_rooms, wall_pair_rooms, wall_pairs
        )


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
        self._deleted_room_ids: set[str] = set()
        self._area_basis: str = "inner"
        self._area_basis: str = "inner"
        self._reviewed_rooms: set[str] = set()  # ユーザーが修正した部屋 ID
        self._room_overlay = RoomOverlayRenderer()
        self._dimension_checks: list[DimensionCheck] = []
        self._dimension_overlay = DimensionOverlayRenderer()
        self._load_thread: Optional[QThread] = None
        self._worker: Optional[DrawingLoadWorker] = None
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

        # 図面を開く（DXF / PDF）
        self._act_open = QAction("📂 図面を開く", self)
        self._act_open.setShortcut(QKeySequence.StandardKey.Open)
        self._act_open.setStatusTip("DXF / PDF ファイルを開いて図面を表示します")
        self._act_open.triggered.connect(self._open_drawing)
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

        # 寸法に合わせて倍率を調整する（PDF のみ）。
        self._act_calibrate = QAction("📐 寸法に合わせて倍率を調整", self)
        self._act_calibrate.setEnabled(False)
        self._act_calibrate.setStatusTip("不一致の寸法から換算率を計算し直し、図面全体を拡大・縮小します（PDFのみ）")
        self._act_calibrate.triggered.connect(self._calibrate_scale)
        toolbar.addAction(self._act_calibrate)

        # 寸法照合の印の表示／非表示。
        self._act_toggle_dimensions = QAction("📐 寸法照合を表示", self)
        self._act_toggle_dimensions.setCheckable(True)
        self._act_toggle_dimensions.setChecked(True)
        self._act_toggle_dimensions.setStatusTip("寸法照合の印の表示／非表示を切り替えます")
        self._act_toggle_dimensions.toggled.connect(self._on_toggle_dimension_overlay)
        toolbar.addAction(self._act_toggle_dimensions)

        toolbar.addSeparator()

        # 図面単位の確認・変更（読み込み後に有効になる）。
        # 変更すると部屋の検出から面積まで再計算される。
        toolbar.addWidget(QLabel("単位"))
        self._units_combo = QComboBox()
        for units in ("mm", "cm", "m", "in", "ft"):
            self._units_combo.addItem(units, units)
        self._units_combo.setEnabled(False)
        self._units_combo.setStatusTip(
            "図面の単位を変更します。変更後は部屋候補と面積を再計算します"
        )
        self._units_combo.currentIndexChanged.connect(self._on_units_changed)
        toolbar.addWidget(self._units_combo)

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
        self._room_panel.room_deleted.connect(self._on_room_deleted)

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

    def _open_drawing(self) -> None:
        """図面ファイル（DXF / PDF）選択ダイアログを開く。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "図面ファイルを開く",
            "",
            "図面ファイル (*.dxf *.DXF *.pdf *.PDF);;DXF ファイル (*.dxf *.DXF);;PDF ファイル (*.pdf *.PDF);;すべてのファイル (*)",
        )
        if not file_path:
            return

        mm_per_pt: Optional[float] = None
        if file_path.lower().endswith(".pdf"):
            result = self._ask_pdf_scale(file_path)
            if result is SCALE_DIALOG_CANCELLED:
                self._log("info", "PDF の読み込みを中止しました。")
                return
            mm_per_pt = result

        self._load_drawing(file_path, mm_per_pt=mm_per_pt)

    def _ask_pdf_scale(self, file_path: str) -> object:
        """PDF を開くときに mm/pt 換算率を尋ねる。

        空欄のまま開くこともできる。その場合は None を返す。
        ダイアログでキャンセルした場合は SCALE_DIALOG_CANCELLED を返す。
        """
        dialog = PdfScaleDialog(self, file_name=os.path.basename(file_path))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return SCALE_DIALOG_CANCELLED
        return dialog.scale_mm_per_pt()

    def _load_dxf(self, file_path: str) -> None:
        """後方互換のための別名（_load_drawing と同じ）。"""
        self._load_drawing(file_path)

    def _load_drawing(self, file_path: str, mm_per_pt: Optional[float] = None) -> None:
        """図面ファイルを読み込む。

        DXF はバックグラウンドスレッドで読み込む。同時に複数の
        読み込みスレッドを起動しないようにし、完了後にスレッドと
        ワーカーの参照を安全に解放する。
        PDF は GUI スレッドで同期的に読み込む。PyMuPDF をワーカー
        スレッドで使うと、テストで稀に落ちることがあるため。
        mm_per_pt は PDF の場合の 1pt あたりの mm 数（未指定は None）。
        """
        if file_path.lower().endswith(".pdf"):
            self._load_pdf_sync(file_path, mm_per_pt)
            return
        if self._room_thread is not None and self._room_thread.isRunning():
            self._log("warn", "部屋候補の解析中は別の図面を開けません。")
            return
        if self._load_thread is not None and self._load_thread.isRunning():
            self._log("warn", "別の図面を読み込み中のため、新しい読み込みを開始しませんでした。")
            return

        self._act_open.setEnabled(False)
        self._act_detect_rooms.setEnabled(False)
        filename = os.path.basename(file_path)
        self._label_file.setText(f"ファイル：{filename}")
        self._label_status.setText("状態：読み込み中...")
        self._log("info", f"図面読み込み開始: {file_path}")

        # バックグラウンドスレッドで読み込み
        self._load_thread = QThread(self)
        self._worker = DrawingLoadWorker(file_path, mm_per_pt=mm_per_pt)
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

    def _load_pdf_sync(self, file_path: str, mm_per_pt: Optional[float]) -> None:
        """PDF を GUI スレッドで同期的に読み込む。

        読み込み中は部屋候補の解析も行わない。失敗時は
        _on_load_error 経由で通知する。
        """
        if self._room_thread is not None and self._room_thread.isRunning():
            self._log("warn", "部屋候補の解析中は別の図面を開けません。")
            return
        if self._load_thread is not None and self._load_thread.isRunning():
            self._log("warn", "別の図面を読み込み中のため、新しい読み込みを開始しませんでした。")
            return

        filename = os.path.basename(file_path)
        self._label_file.setText(f"ファイル：{filename}")
        self._label_status.setText("状態：読み込み中...")
        self._log("info", f"図面読み込み開始: {file_path}")
        try:
            drawing = PdfParser().parse(file_path, scale_mm_per_pt=mm_per_pt)
        except Exception as exc:
            logger.exception("PDF の読み込みに失敗しました")
            self._on_load_error(file_path, str(exc))
            return
        self._on_load_finished(file_path, drawing)

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
        self._reviewed_rooms = set()
        self._deleted_room_ids = set()
        self._area_basis = "inner"
        self._room_overlay.clear(self._scene)
        self._dimension_checks = []
        self._dimension_overlay.clear(self._scene)
        self._room_panel.clear()
        self._room_panel.set_area_basis("inner")
        self._act_export_rooms.setEnabled(False)
        self._act_detect_rooms.setEnabled(True)
        self._units_combo.blockSignals(True)
        self._units_combo.setCurrentIndex(self._units_combo.findData(drawing.units))
        self._units_combo.blockSignals(False)
        self._units_combo.setEnabled(True)
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
        if drawing.file_type == "pdf":
            self._log("info", f"読み込み完了: {stats.total_elements} 要素 / レイヤー数: {stats.layer_count} / PDF（{meta.get('pdf_page_count', 1)} ページ中 1 ページ目）")
            self._run_dimension_check()
            self._rerender_dimension_overlay()
            self._update_calibrate_action()
            scanned_warning = meta.get("scanned_pdf_warning")
            if scanned_warning:
                self._log("warn", scanned_warning)
            text_warning = meta.get("text_garbled_warning")
            if text_warning:
                self._log("warn", text_warning)
        else:
            dxf_ver = meta.get("dxf_version", "不明")
            unsupported = meta.get("unsupported_types", {})
            self._log("info", f"読み込み完了: {stats.total_elements} 要素 / レイヤー数: {stats.layer_count} / DXFバージョン: {dxf_ver}")
            self._act_calibrate.setEnabled(False)
            if unsupported:
                self._log("warn", f"未対応エンティティ（スキップ）: {unsupported}")
        self._log("info", f"要素内訳: {stats.by_type}")
        units_warning = meta.get("units_warning")
        if units_warning:
            self._log("warn", units_warning)

    def _run_dimension_check(self) -> list:
        """現在の図面について寸法照合を実行し、結果を保持してログに出す。"""
        if self._drawing is None:
            self._dimension_checks = []
            return []
        try:
            checks = check_dimensions(self._drawing)
        except Exception as exc:
            logger.exception("寸法照合に失敗しました")
            self._log("warn", f"寸法照合に失敗しました: {exc}")
            self._dimension_checks = []
            return []
        self._dimension_checks = checks
        matched = sum(1 for c in checks if c.status == "matched")
        mismatched = sum(1 for c in checks if c.status == "mismatched")
        to_confirm = sum(1 for c in checks if c.status == "to_confirm")
        not_determinable = sum(1 for c in checks if c.status == "not_determinable")
        self._log(
            "info",
            f"寸法照合: {len(checks)} 件（一致 {matched}、不一致 {mismatched}、"
            f"要確認 {to_confirm}、判定不能 {not_determinable}）",
        )
        return checks

    def _rerender_dimension_overlay(self) -> None:
        """現在の寸法照合の結果でオーバーレイを描き直す。"""
        self._dimension_overlay.clear(self._scene)
        if self._drawing is not None and self._dimension_checks:
            self._dimension_overlay.render_checks(
                self._dimension_checks, self._drawing, self._scene
            )
        self._dimension_overlay.set_visible(self._act_toggle_dimensions.isChecked())

    def _update_calibrate_action(self) -> None:
        """倍率調整ボタンの有効／無効を現在の照合結果に合わせる。"""
        enabled = (
            self._drawing is not None
            and self._drawing.file_type == "pdf"
            and any(
                c.status == "mismatched" and c.measured_length_pt
                for c in self._dimension_checks
            )
        )
        self._act_calibrate.setEnabled(bool(enabled))

    def _on_toggle_dimension_overlay(self, checked: bool) -> None:
        """寸法照合の印の表示／非表示を切り替える。"""
        self._dimension_overlay.set_visible(checked)

    def _calibrate_scale(self) -> None:
        """不一致の寸法から換算率を計算し直し、図面全体を拡大・縮小する。

        倍率調整はこのボタンの操作でのみ行い、自動では行わない。
        調整後は図面を描き直し、寸法照合と部屋検出をやり直す。
        """
        if self._drawing is None or self._drawing.file_type != "pdf":
            QMessageBox.information(self, "倍率調整", "倍率調整は PDF の図面でのみ行えます。")
            return
        candidates = [
            c for c in self._dimension_checks
            if c.status == "mismatched" and c.measured_length_pt
        ]
        if not candidates:
            QMessageBox.information(
                self,
                "倍率調整",
                "調整対象の寸法がありません。\n"
                "（不一致の寸法がないか、測定対象の線が見つかっていません）",
            )
            self._log("info", "倍率調整：調整対象の寸法がないため、何もしませんでした。")
            return
        check = max(candidates, key=lambda c: c.confidence)
        meta = getattr(self._drawing, "_meta", {})
        current_mm_per_pt = float(meta.get("mm_per_pt") or self._drawing.scale or 1.0)
        try:
            new_mm_per_pt = calibrate_scale_from_dimension(check, current_mm_per_pt)
            factor = rescale_drawing(self._drawing, new_mm_per_pt, source_check=check)
        except ValueError as exc:
            QMessageBox.warning(self, "倍率調整", f"換算率を計算できませんでした。\n{exc}")
            return
        self._log(
            "info",
            f"倍率調整：{check.dimension_id}（寸法 {check.value_mm:.0f}mm／実測 {check.measured_mm:.0f}mm）を使い、"
            f"換算率を {current_mm_per_pt:.6f} → {new_mm_per_pt:.6f} mm/pt（倍率 {factor:.6f}）に変更しました。",
        )
        # 図面を描き直し、寸法照合と部屋検出をやり直す。
        self._renderer.render(self._drawing, self._scene)
        self._run_dimension_check()
        self._rerender_dimension_overlay()
        self._update_calibrate_action()
        self._fit_view()
        self._detect_room_candidates()
        QMessageBox.information(
            self,
            "倍率調整",
            f"換算率を {current_mm_per_pt:.4f} → {new_mm_per_pt:.4f} mm/pt に変更しました。\n"
            f"（{check.dimension_id}：寸法 {check.value_mm:.0f}mm／実測 {check.measured_mm:.0f}mm）\n"
            f"寸法照合と部屋検出をやり直しています。",
        )

    def _on_load_error(self, file_path: str, message: str) -> None:
        """図面読み込みエラー時の処理。"""
        self._label_status.setText("状態：読み込みエラー")
        # 読み込みに失敗したファイルを、現在表示中の図面として表示しない。
        current_name = os.path.basename(self._current_file) if self._current_file else "（未選択）"
        self._label_file.setText(f"ファイル：{current_name}")
        self._update_title()
        self._log("error", f"読み込みエラー: {message}")

        QMessageBox.warning(
            self,
            "図面読み込みエラー",
            f"図面ファイルを読み込めませんでした。\n\n"
            f"原因：\nこの図面形式は現在対応していない可能性があります。\n\n"
            f"詳細：\n{message}",
        )

    def _detect_room_candidates(self) -> None:
        """GUIをブロックせずに暫定的な部屋候補を検出する。"""
        if self._drawing is None or self._room_thread is not None:
            return
        if self._load_thread is not None:
            # 読み込み中の検出は古い図面を対象にし、読み込み完了時に
            # 結果が消えてしまうため、読み込みが終わるまで待つ。
            self._log("warn", "図面の読み込み中のため、部屋候補の検出を後でもう一度行ってください。")
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
        self._room_worker.progress.connect(self._on_room_detection_progress)
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

    @Slot(str)
    def _on_room_detection_progress(self, message: str) -> None:
        """検出の進行状況をステータスバーとログへ表示する。

        線分検出は実図面で数分かかるため、どの段階にいるかを示す。
        """
        self._label_status.setText(f"状態：{message}")
        self._log("info", message)

    @Slot(object, object, object, object)
    def _on_room_detection_finished(
        self,
        polyline_rooms: list,
        linework_rooms: list,
        wall_pair_rooms: list,
        wall_pairs: list,
    ) -> None:
        self._label_status.setText("状態：部屋候補の解析完了")
        rooms = deduplicate_room_candidates(polyline_rooms, linework_rooms)
        rooms = merge_room_candidates(rooms, wall_pair_rooms)
        if self._drawing is not None:
            rooms = associate_room_names(self._drawing, rooms)
        self._reviewed_rooms = set()
        # 以前に保存した確認内容があれば、検出直後の部屋へ適用する。
        if self._current_file is not None:
            saved = load_reviews(self._current_file)
            applied = apply_reviews(rooms, saved)
            self._reviewed_rooms = {r.room_id for r in rooms if r.room_id in saved}
            if applied:
                self._log("info", f"保存されていた確認内容を {applied} 件の部屋に適用しました。")
        # このセッションで削除した部屋は、再検出でも復活させない。
        if self._deleted_room_ids:
            rooms = [r for r in rooms if r.room_id not in self._deleted_room_ids]
        self._rooms = rooms
        # 検出ワーカーで求めた二重線の壁を使い、壁芯面積が求まる部屋へ付与する。
        # 壁の検出に失敗しても部屋候補の表示は妨げない。
        if self._drawing is not None and wall_pairs:
            try:
                factor = area_factor_for_units(self._drawing.units)
                attached = attach_wall_info(rooms, wall_pairs, factor)
                self._log(
                    "info",
                    f"二重線の壁: {len(wall_pairs)} 組 / 壁芯面積を算出できた部屋: {attached} 件",
                )
            except Exception as exc:
                logger.exception("二重線の壁の検出に失敗しました")
                self._log("warn", f"二重線の壁の検出に失敗しました: {exc}")
        self._log("info", f"部屋候補: ポリライン {len(polyline_rooms)} 件 / 線分 {len(linework_rooms)} 件 / 壁ペア線分 {len(wall_pair_rooms)} 件")
        if not rooms:
            self._room_overlay.clear(self._scene)
            self._room_panel.clear()
            self._act_export_rooms.setEnabled(False)
            QMessageBox.information(self, "部屋候補の検出", "閉じた領域候補は見つかりませんでした。")
            return
        # 図面上に部屋候補を重ねて表示し、部屋一覧パネルに反映する。
        self._room_overlay.clear(self._scene)
        self._room_overlay.render_rooms(rooms, self._scene, self._area_basis)
        # 全体表示ではラベルが重なって読めなくなるため、重なるラベルは
        # 大きい部屋のものだけを残して隠す。
        self._room_overlay.update_label_visibility(self._view)
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
        # ズームに応じて重なる部屋ラベルの表示を入れ替える。
        self._room_overlay.update_label_visibility(self._view)

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
        dimension_id = item.data(DIMENSION_ITEM_ROLE)
        if dimension_id:
            check = next(
                (c for c in self._dimension_checks if c.dimension_id == dimension_id),
                None,
            )
            if check is not None:
                self._property_panel.show_dimension_check(check)
                self._right_tabs.setCurrentWidget(self._property_panel)
                return
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

    def _on_units_changed(self, _index: int) -> None:
        """図面単位の変更を検出結果と面積へ反映する。"""
        if self._drawing is None:
            return
        new_units = self._units_combo.currentData()
        if new_units not in ("mm", "cm", "m", "in", "ft"):
            return
        if new_units == self._drawing.units:
            return
        if self._room_thread is not None:
            self._log("warn", "部屋候補の解析中のため、単位の変更を後でもう一度行ってください。")
            self._units_combo.blockSignals(True)
            self._units_combo.setCurrentIndex(self._units_combo.findData(self._drawing.units))
            self._units_combo.blockSignals(False)
            return
        old_units = self._drawing.units
        self._drawing.units = new_units
        meta = getattr(self._drawing, "_meta", {})
        meta["units_source"] = "user_override"
        meta.pop("units_warning", None)
        self._label_coords.setText(
            f"座標：(0.00, 0.00) {self._coordinate_unit_suffix()}"
        )
        self._log("info", f"図面単位を {old_units} から {new_units} に変更しました。部屋候補を再計算します。")
        self._detect_room_candidates()

    def _on_room_deleted(self, room_id: str) -> None:
        """削除された部屋を一覧と図面から取り除く。

        削除はこのセッション内のみ有効で、図面を読み込み直すと
        検出からやり直す。削除の保存は、確認内容の保存とあわせて
        対応する予定。
        """
        self._rooms = [room for room in self._rooms if room.room_id != room_id]
        self._deleted_room_ids.add(room_id)
        self._area_basis = self._room_panel.area_basis
        self._rerender_room_overlay()
        self._act_export_rooms.setEnabled(bool(self._rooms))
        self._label_status.setText(f"状態：部屋候補 {len(self._rooms)} 件")
        self._log("info", f"部屋候補を削除しました：{room_id}（残り {len(self._rooms)} 件）")

    def _on_room_panel_selected(self, room_id: str) -> None:
        """部屋一覧パネルで部屋が選ばれたら、図面上の該当オーバーレイを選択する。"""
        self._scene.clearSelection()
        for item in self._scene.items():
            if item.data(ROOM_ITEM_ROLE) == room_id:
                item.setSelected(True)
                break

    def _on_room_name_changed(self, room_id: str, _new_name: str) -> None:
        """部屋名の編集をオーバーレイへ反映し、保存する。"""
        self._reviewed_rooms.add(room_id)
        self._save_reviews()
        self._rerender_room_overlay()

    def _on_room_status_changed(self, room_id: str, _new_status: str) -> None:
        """確認状態の変更をオーバーレイへ反映し、保存する。"""
        self._reviewed_rooms.add(room_id)
        self._save_reviews()
        self._rerender_room_overlay()

    def _save_reviews(self) -> None:
        """現在の確認内容を DXF 横の保存ファイルへ書き出す。

        保存に失敗しても作業は続けられるよう、警告ログに留める。
        """
        if self._current_file is None or not self._rooms:
            return
        try:
            save_reviews(self._current_file, self._rooms, self._reviewed_rooms)
        except OSError as exc:
            logger.exception("部屋の確認内容の保存に失敗しました")
            self._log("warn", f"確認内容を保存できませんでした（{exc}）。図面フォルダへの書き込み権限を確認してください。")

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
        self._log_handler = _QtLogHandler(self._log_text)
        self._log_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
        self._log_handler.setFormatter(formatter)
        logging.getLogger().addHandler(self._log_handler)
        logging.getLogger().setLevel(logging.DEBUG)

    def closeEvent(self, event) -> None:
        """ウィンドウを閉じるとき、ログハンドラーを外す。

        外さないと、削除済みのウィンドウへログを送ろうとして
        エラーが繰り返し出る。
        """
        handler = getattr(self, "_log_handler", None)
        if handler is not None:
            logging.getLogger().removeHandler(handler)
            self._log_handler = None
        super().closeEvent(event)

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
        except RuntimeError:
            # ブリッジ（ウィンドウ）が削除済みの場合はログを捨てる。
            return
        except Exception:
            self.handleError(record)
