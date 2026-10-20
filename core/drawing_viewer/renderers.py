"""
core.drawing_viewer.renderers
Drawing モデルの各 DrawingElement を QGraphicsItem へ変換するレンダラー。
DXFのY軸（上向き）→ 画面座標のY軸（下向き）への変換（y → -y）もここで行います。
"""

import math
import logging
from typing import List, Optional

from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsLineItem, QGraphicsPathItem,
    QGraphicsEllipseItem, QGraphicsSimpleTextItem, QGraphicsItemGroup
)
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPen, QColor, QPainterPath, QFont

from core.models.drawing import (
    Drawing, DrawingElement, LineElement, PolylineElement,
    TextElement, CircleElement, ArcElement, InsertElement
)
from core.drawing_viewer.scene import DrawingScene, DrawingLayer

logger = logging.getLogger(__name__)

# DXF ACI カラーコードの簡易マッピング（AutoCAD Color Index → QColor）
_ACI_COLORS = {
    1:  "#FF0000",  # 赤
    2:  "#FFFF00",  # 黄
    3:  "#00FF00",  # 緑
    4:  "#00FFFF",  # シアン
    5:  "#0000FF",  # 青
    6:  "#FF00FF",  # マゼンタ
    7:  "#FFFFFF",  # 白（7 = 白/黒）
    8:  "#808080",  # グレー
    9:  "#C0C0C0",  # ライトグレー
}
DEFAULT_LINE_COLOR = QColor("#c0caf5")   # デフォルト線色（ダークテーマ対応）
DEFAULT_TEXT_COLOR = QColor("#e0af68")   # テキスト色
DEFAULT_LINE_WIDTH = 0.0                 # 0 = cosmetic pen（常に1px幅）


class DxfRenderer:
    """
    Drawing モデルの要素を QGraphicsItem へ変換し、DrawingScene の BASE レイヤーへ追加するレンダラー。
    """

    def __init__(self):
        self._layer_items: dict[str, list[QGraphicsItem]] = {}

    def render(self, drawing: Drawing, scene: DrawingScene) -> None:
        """
        Drawing オブジェクトの全要素を scene の BASE レイヤーに描画する。
        
        Args:
            drawing: 描画対象の Drawing オブジェクト
            scene: 描画先の DrawingScene
        """
        scene.clear_layer(DrawingLayer.BASE)
        self._layer_items.clear()

        rendered = 0
        skipped = 0

        for element in drawing.elements:
            item = self._create_item(element)
            if item is not None:
                # 要素IDと選択可能性を設定
                item.setData(Qt.ItemDataRole.UserRole, element.element_id)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

                scene.add_to_layer(item, DrawingLayer.BASE)
                rendered += 1

                # レイヤー毎に保管
                layer_name = element.layer or "0"
                if layer_name not in self._layer_items:
                    self._layer_items[layer_name] = []
                self._layer_items[layer_name].append(item)
            else:
                skipped += 1

        logger.info("描画完了: %d 要素描画, %d 要素スキップ", rendered, skipped)

    def set_layer_visible(self, layer_name: str, visible: bool) -> None:
        """指定したレイヤーの描画アイテムの表示/非表示を切り替える。"""
        if layer_name in self._layer_items:
            for item in self._layer_items[layer_name]:
                item.setVisible(visible)

    # ------------------------------------------------------------------
    # プライベートメソッド
    # ------------------------------------------------------------------

    def _create_item(self, element: DrawingElement) -> Optional[QGraphicsItem]:
        """DrawingElement の種類に応じた QGraphicsItem を生成する。"""
        try:
            if isinstance(element, LineElement):
                return self._create_line(element)
            elif isinstance(element, PolylineElement):
                return self._create_polyline(element)
            elif isinstance(element, ArcElement):
                return self._create_arc(element)
            elif isinstance(element, CircleElement):
                return self._create_circle(element)
            elif isinstance(element, TextElement):
                return self._create_text(element)
            elif isinstance(element, InsertElement):
                return self._create_insert(element)
            else:
                logger.debug("未対応要素タイプ: %s", element.element_type)
                return None
        except Exception as e:
            logger.warning("描画アイテム生成失敗 (%s): %s", element.element_id, e)
            return None

    def _get_pen(self, element: DrawingElement, width: float = DEFAULT_LINE_WIDTH) -> QPen:
        """要素のカラーコードから QPen を生成する。"""
        color_code = element.color
        if color_code is not None and int(color_code) in _ACI_COLORS:
            color = QColor(_ACI_COLORS[int(color_code)])
        else:
            color = DEFAULT_LINE_COLOR

        pen = QPen(color)
        pen.setWidthF(width)
        pen.setCosmetic(True)  # ズームに関わらず常に一定の画面幅で描画
        return pen

    @staticmethod
    def _y(y: float) -> float:
        """DXF（Y上向き）→ 画面座標（Y下向き）のY軸反転。"""
        return -y

    def _create_line(self, element: LineElement) -> QGraphicsLineItem:
        item = QGraphicsLineItem(
            element.start[0], self._y(element.start[1]),
            element.end[0],   self._y(element.end[1]),
        )
        item.setPen(self._get_pen(element))
        return item

    def _create_polyline(self, element: PolylineElement) -> Optional[QGraphicsPathItem]:
        if len(element.points) < 2:
            return None

        path = QPainterPath()
        path.moveTo(element.points[0][0], self._y(element.points[0][1]))
        for pt in element.points[1:]:
            path.lineTo(pt[0], self._y(pt[1]))

        if element.is_closed and len(element.points) >= 2:
            path.closeSubpath()

        item = QGraphicsPathItem(path)
        item.setPen(self._get_pen(element))
        item.setBrush(QColor(0, 0, 0, 0))  # 透明塗りつぶし
        return item

    def _create_arc(self, element: ArcElement) -> QGraphicsPathItem:
        """
        DXFの円弧をQPainterPathで描画する。
        DXFの角度はデカルト座標系（反時計回り）、Qtのarcは時計回り（Y軸反転のため）。
        """
        cx = element.center[0]
        cy = self._y(element.center[1])
        r = element.radius

        # Y軸反転により角度の向きが反転するため調整
        start_angle = element.start_angle
        end_angle = element.end_angle

        # Qt の drawArc は角度を1/16度単位、反時計回りで指定
        # Y反転後は: 角度 = -(元の角度)
        qt_start = -start_angle
        span = end_angle - start_angle
        if span <= 0:
            span += 360.0
        qt_span = -span

        path = QPainterPath()
        rect = QRectF(cx - r, cy - r, r * 2, r * 2)
        path.arcMoveTo(rect, qt_start)
        path.arcTo(rect, qt_start, qt_span)

        item = QGraphicsPathItem(path)
        item.setPen(self._get_pen(element))
        item.setBrush(QColor(0, 0, 0, 0))
        return item

    def _create_circle(self, element: CircleElement) -> QGraphicsEllipseItem:
        cx = element.center[0]
        cy = self._y(element.center[1])
        r = element.radius
        item = QGraphicsEllipseItem(cx - r, cy - r, r * 2, r * 2)
        item.setPen(self._get_pen(element))
        item.setBrush(QColor(0, 0, 0, 0))
        return item

    def _create_text(self, element: TextElement) -> QGraphicsSimpleTextItem:
        item = QGraphicsSimpleTextItem(element.text)

        # フォントサイズはDXFのheight（mm単位）をそのままptとして使用
        # 将来的に座標変換が入る場合はここで換算する
        font = QFont("Yu Gothic UI", max(1, int(element.height)))
        item.setFont(font)
        item.setBrush(DEFAULT_TEXT_COLOR)

        # 配置（Y反転、テキスト高さ分だけ上にオフセット）
        x = element.insertion_point[0]
        y = self._y(element.insertion_point[1]) - element.height

        # 回転がある場合（Y反転後なので符号反転）
        if element.rotation != 0.0:
            item.setRotation(-element.rotation)

        item.setPos(x, y)
        return item

    def _create_insert(self, element: InsertElement) -> QGraphicsItemGroup:
        group = QGraphicsItemGroup()
        x = element.insert_point[0]
        y = self._y(element.insert_point[1])
        s = 50.0  # ブロック挿入点用の標準マーカーサイズ (50mm)
        pen = self._get_pen(element)

        l1 = QGraphicsLineItem(x - s, y, x + s, y)
        l2 = QGraphicsLineItem(x, y - s, x, y + s)
        l1.setPen(pen)
        l2.setPen(pen)
        group.addToGroup(l1)
        group.addToGroup(l2)

        text = QGraphicsSimpleTextItem(f"[{element.block_name}]")
        font = QFont("Yu Gothic UI", 12)
        text.setFont(font)
        text.setBrush(DEFAULT_TEXT_COLOR)
        text.setPos(x + s * 0.5, y - s * 0.5)
        group.addToGroup(text)

        return group

