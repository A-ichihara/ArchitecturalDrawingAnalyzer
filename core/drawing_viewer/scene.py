"""
core.drawing_viewer.scene
4レイヤー構造を持つ QGraphicsScene サブクラス。
将来の解析結果・差分・ユーザー注釈の追加に対応します。
"""

from enum import IntEnum
from typing import Optional, List

from PySide6.QtWidgets import QGraphicsScene, QGraphicsItemGroup, QGraphicsItem
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPen


class DrawingLayer(IntEnum):
    """描画レイヤーのZオーダー定義"""
    BASE = 0        # DXF/PDF図面の基本要素
    ANALYSIS = 10   # 解析結果（部屋境界・壁芯・面積）
    CHANGE = 20     # 差分表示（赤丸・ハイライト）
    ANNOTATION = 30 # ユーザー注釈


class DrawingScene(QGraphicsScene):
    """
    図面表示用 QGraphicsScene。
    各レイヤーを QGraphicsItemGroup で管理し、
    将来的なレイヤーの表示/非表示切り替えを容易にします。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackgroundBrush(QColor("#1e1e2e"))  # ダークテーマ背景

        # レイヤーグループの初期化
        self._layers: dict[int, QGraphicsItemGroup] = {}
        for layer_id in DrawingLayer:
            group = self.addItem_group()
            group.setZValue(float(layer_id))
            self._layers[int(layer_id)] = group

    def addItem_group(self) -> QGraphicsItemGroup:
        """グループアイテムを生成してシーンに追加する。"""
        group = QGraphicsItemGroup()
        self.addItem(group)
        return group

    def add_to_layer(self, item: QGraphicsItem, layer: DrawingLayer) -> None:
        """
        指定レイヤーにアイテムを追加する。
        
        Args:
            item: 追加する QGraphicsItem
            layer: 追加先の DrawingLayer
        """
        group = self._layers.get(int(layer))
        if group is not None:
            group.addToGroup(item)
        else:
            self.addItem(item)

    def clear_layer(self, layer: DrawingLayer) -> None:
        """指定レイヤーのアイテムをすべて削除する。"""
        group = self._layers.get(int(layer))
        if group is None:
            return
        for item in group.childItems():
            group.removeFromGroup(item)
            self.removeItem(item)

    def clear_all_layers(self) -> None:
        """全レイヤーのアイテムを削除する。"""
        for layer in DrawingLayer:
            self.clear_layer(layer)

    def set_layer_visible(self, layer: DrawingLayer, visible: bool) -> None:
        """指定レイヤーの表示/非表示を切り替える。"""
        group = self._layers.get(int(layer))
        if group is not None:
            group.setVisible(visible)

    def get_drawing_bounds(self) -> QRectF:
        """BASE レイヤーのバウンディングボックスを返す。"""
        base_group = self._layers.get(int(DrawingLayer.BASE))
        if base_group is None or not base_group.childItems():
            return self.sceneRect()
        return base_group.boundingRect()
