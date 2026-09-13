"""
core.drawing_viewer.view
ズーム・パン操作を提供する QGraphicsView サブクラス。
マウスホイールでマウスカーソル位置中心の拡大縮小、
中ボタンドラッグでパン操作を実現します。
"""

from PySide6.QtWidgets import QGraphicsView
from PySide6.QtCore import Qt, QPointF, Signal
from PySide6.QtGui import QPainter, QWheelEvent, QMouseEvent, QKeyEvent

# ズームの倍率制限
ZOOM_MIN = 0.01   # 1%
ZOOM_MAX = 100.0  # 10000%
ZOOM_STEP = 1.15  # 1ステップあたりの倍率


class DrawingView(QGraphicsView):
    """
    ズーム・パン操作対応の図面ビュー。
    
    操作方法:
        - マウスホイール: ズームイン/アウト（カーソル位置中心）
        - 中ボタンドラッグ: パン（移動）
        - Space + 左ボタンドラッグ: パン（代替）
    """

    zoom_changed = Signal(float)  # ズーム倍率変更シグナル（UIへの通知用）

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)

        # レンダリング品質設定
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # スクロールバーを非表示（自前でパン管理）
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # 変換の基準点を設定（マウス位置中心ズーム用）
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)

        self.setDragMode(QGraphicsView.DragMode.NoDrag)

        # パン操作の状態管理
        self._panning = False
        self._pan_start: QPointF = QPointF()
        self._space_pressed = False

        # 現在のズーム倍率
        self._zoom_factor = 1.0

    # ------------------------------------------------------------------
    # 公開メソッド
    # ------------------------------------------------------------------

    def fit_in_view(self) -> None:
        """図面全体が表示エリアに収まるようにビューを調整する。"""
        scene = self.scene()
        if scene is None:
            return

        # BASE レイヤーのバウンディングボックスを取得
        if hasattr(scene, "get_drawing_bounds"):
            rect = scene.get_drawing_bounds()
        else:
            rect = scene.itemsBoundingRect()

        if rect.isNull() or rect.isEmpty():
            return

        self.resetTransform()
        self._zoom_factor = 1.0

        # マージンを追加して fitInView を実行
        margin = max(rect.width(), rect.height()) * 0.05
        padded = rect.adjusted(-margin, -margin, margin, margin)
        self.fitInView(padded, Qt.AspectRatioMode.KeepAspectRatio)

        # 現在のズーム倍率を計算して記録
        tr = self.transform()
        self._zoom_factor = tr.m11()
        self.zoom_changed.emit(self._zoom_factor)

    def zoom_in(self) -> None:
        """ズームイン（ビュー中心）"""
        self._apply_zoom(ZOOM_STEP, self.viewport().rect().center())

    def zoom_out(self) -> None:
        """ズームアウト（ビュー中心）"""
        self._apply_zoom(1.0 / ZOOM_STEP, self.viewport().rect().center())

    def current_zoom_percent(self) -> float:
        """現在のズーム倍率をパーセント値で返す。"""
        return self._zoom_factor * 100.0

    # ------------------------------------------------------------------
    # イベントハンドラ
    # ------------------------------------------------------------------

    def wheelEvent(self, event: QWheelEvent) -> None:
        """マウスホイールによるズーム操作。カーソル位置を中心に拡大縮小する。"""
        delta = event.angleDelta().y()
        if delta == 0:
            return

        factor = ZOOM_STEP if delta > 0 else 1.0 / ZOOM_STEP

        # ズーム倍率の上下限チェック
        new_zoom = self._zoom_factor * factor
        if new_zoom < ZOOM_MIN or new_zoom > ZOOM_MAX:
            return

        # マウス位置を基準にズーム
        cursor_pos = event.position()
        self._apply_zoom(factor, cursor_pos)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """中ボタン または Space+左ボタン でパン開始。"""
        if (event.button() == Qt.MouseButton.MiddleButton
                or (self._space_pressed and event.button() == Qt.MouseButton.LeftButton)):
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """パン中の移動処理。"""
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            # スクロールバーを動かす代わりにビュー変換を移動
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """パン終了。"""
        if self._panning and (
            event.button() == Qt.MouseButton.MiddleButton
            or event.button() == Qt.MouseButton.LeftButton
        ):
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Spaceキー押下でパンモードへ移行。"""
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pressed = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        """Spaceキー解放でパンモード終了。"""
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pressed = False
            if not self._panning:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            super().keyReleaseEvent(event)

    # ------------------------------------------------------------------
    # プライベートメソッド
    # ------------------------------------------------------------------

    def _apply_zoom(self, factor: float, anchor_point) -> None:
        """
        anchor_point（ビューポート座標）を中心にズームを適用する。
        
        Args:
            factor: ズーム倍率（>1で拡大、<1で縮小）
            anchor_point: QPointF または QPoint（ビューポート座標）
        """
        new_zoom = self._zoom_factor * factor
        if new_zoom < ZOOM_MIN or new_zoom > ZOOM_MAX:
            return

        # アンカー位置のシーン座標を記憶
        scene_anchor = self.mapToScene(int(anchor_point.x()), int(anchor_point.y()))

        self.scale(factor, factor)
        self._zoom_factor = new_zoom

        # ズーム後にアンカー位置がずれないよう調整
        new_scene_anchor = self.mapToScene(int(anchor_point.x()), int(anchor_point.y()))
        delta = new_scene_anchor - scene_anchor
        self.translate(delta.x(), delta.y())

        self.zoom_changed.emit(self._zoom_factor)
