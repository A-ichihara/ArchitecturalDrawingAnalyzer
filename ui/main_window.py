"""
ui.main_window
建築図面解析・設備設計支援システムのメインウィンドウ。
ツールバー、Drawing Viewer、ステータスバーで構成されます。
"""

import logging
import os
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QToolBar, QStatusBar, QFileDialog, QMessageBox,
    QLabel, QSizePolicy, QDockWidget, QTextEdit, QPushButton
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QAction, QIcon, QKeySequence, QColor

from core.drawing_viewer.scene import DrawingScene
from core.drawing_viewer.view import DrawingView
from core.drawing_viewer.renderers import DxfRenderer
from core.parser.dxf_parser import DxfParser
from core.models.drawing import Drawing

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# バックグラウンドDXF読み込みワーカー
# ---------------------------------------------------------------------------

class DxfLoadWorker(QObject):
    """DXFファイルをバックグラウンドスレッドで読み込むワーカー。"""
    finished = Signal(object)   # Drawing オブジェクト
    error = Signal(str)         # エラーメッセージ

    def __init__(self, file_path: str):
        super().__init__()
        self._file_path = file_path

    def run(self) -> None:
        try:
            parser = DxfParser()
            drawing = parser.parse(self._file_path)
            self.finished.emit(drawing)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# メインウィンドウ
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """
    建築図面解析・設備設計支援システム メインウィンドウ。
    
    構成:
        - ツールバー: [DXFを開く] [全体表示] [ズームイン] [ズームアウト]
        - 中央: DrawingView（DXF図面表示エリア）
        - 下部ステータスバー: ファイル名・状態・ズーム率
        - 右ドック: ログ表示エリア（開発確認用）
    """

    APP_TITLE = "建築図面解析・設備設計支援システム"
    VERSION = "Phase 1"

    def __init__(self):
        super().__init__()
        self._current_file: Optional[str] = None
        self._drawing: Optional[Drawing] = None
        self._load_thread: Optional[QThread] = None

        self._setup_ui()
        self._setup_logging()
        self._update_title()

    # ------------------------------------------------------------------
    # UI構築
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle(self.APP_TITLE)
        self.resize(1280, 800)
        self._apply_stylesheet()

        # シーン＋ビュー
        self._scene = DrawingScene()
        self._view = DrawingView(self._scene, self)
        self._renderer = DxfRenderer()

        # ツールバー
        self._setup_toolbar()

        # 中央ウィジェット
        self.setCentralWidget(self._view)

        # ステータスバー
        self._setup_statusbar()

        # ログドック
        self._setup_log_dock()

        # ズーム変化シグナル接続
        self._view.zoom_changed.connect(self._on_zoom_changed)

    def _setup_toolbar(self) -> None:
        toolbar = QToolBar("メインツールバー", self)
        toolbar.setMovable(False)
        toolbar.setStyleSheet("QToolBar { spacing: 6px; padding: 4px; }")
        self.addToolBar(toolbar)

        # DXFを開く
        act_open = QAction("📂 DXFを開く", self)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.setStatusTip("DXFファイルを開いて図面を表示します")
        act_open.triggered.connect(self._open_dxf)
        toolbar.addAction(act_open)

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

    def _setup_statusbar(self) -> None:
        statusbar = QStatusBar()
        self.setStatusBar(statusbar)

        self._label_file = QLabel("ファイル：（未選択）")
        self._label_status = QLabel("状態：待機中")
        self._label_elements = QLabel("")
        self._label_zoom = QLabel("ズーム：100%")

        statusbar.addWidget(self._label_file, 2)
        statusbar.addWidget(self._label_status, 2)
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
                titlebar-close-icon: url(none.png);
            }
            QDockWidget::title {
                background: #16213e;
                padding: 4px;
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
        """DXFファイルをバックグラウンドで読み込む。"""
        self._current_file = file_path
        filename = os.path.basename(file_path)
        self._label_file.setText(f"ファイル：{filename}")
        self._label_status.setText("状態：読み込み中...")
        self._log("info", f"DXF読み込み開始: {file_path}")
        self._update_title()

        # バックグラウンドスレッドで読み込み
        self._load_thread = QThread(self)
        self._worker = DxfLoadWorker(file_path)
        self._worker.moveToThread(self._load_thread)
        self._load_thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_load_finished)
        self._worker.error.connect(self._on_load_error)
        self._worker.finished.connect(self._load_thread.quit)
        self._worker.error.connect(self._load_thread.quit)
        self._load_thread.start()

    def _on_load_finished(self, drawing: Drawing) -> None:
        """DXF読み込み完了時の処理。"""
        self._drawing = drawing

        # レンダリング
        self._renderer.render(drawing, self._scene)

        # ビューを図面全体に合わせる
        self._fit_view()

        # ステータス更新
        elem_count = len(drawing.elements)
        self._label_status.setText("状態：表示完了")
        self._label_elements.setText(f"要素数：{elem_count}")

        meta = getattr(drawing, "_meta", {})
        dxf_ver = meta.get("dxf_version", "不明")
        unsupported = meta.get("unsupported_types", {})

        self._log("info", f"読み込み完了: {elem_count} 要素 / DXFバージョン: {dxf_ver}")
        if unsupported:
            self._log("warn", f"未対応エンティティ（スキップ）: {unsupported}")

    def _on_load_error(self, message: str) -> None:
        """DXF読み込みエラー時の処理。"""
        self._label_status.setText("状態：読み込みエラー")
        self._log("error", f"読み込みエラー: {message}")

        QMessageBox.warning(
            self,
            "DXF読み込みエラー",
            f"DXFファイルを読み込めませんでした。\n\n"
            f"原因：\nこのDXF形式は現在対応していない可能性があります。\n\n"
            f"詳細：\n{message}",
        )

    def _fit_view(self) -> None:
        """全体表示を実行する。"""
        self._view.fit_in_view()

    def _on_zoom_changed(self, zoom: float) -> None:
        """ズーム倍率変更時にステータスバーを更新する。"""
        self._label_zoom.setText(f"ズーム：{zoom * 100:.1f}%")

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
# カスタムログハンドラ
# ---------------------------------------------------------------------------

class _QtLogHandler(logging.Handler):
    """Pythonのloggingメッセージを QTextEdit に出力するハンドラー。"""

    COLOR_MAP = {
        logging.DEBUG:    "#565f89",
        logging.INFO:     "#a9b1d6",
        logging.WARNING:  "#e0af68",
        logging.ERROR:    "#f7768e",
        logging.CRITICAL: "#ff007c",
    }

    def __init__(self, widget: QTextEdit):
        super().__init__()
        self._widget = widget

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            color = self.COLOR_MAP.get(record.levelno, "#a9b1d6")
            self._widget.append(f'<span style="color:{color};">{msg}</span>')
        except Exception:
            pass
