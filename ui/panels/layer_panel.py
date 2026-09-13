"""
ui.panels.layer_panel
DXF図面内のレイヤー一覧・表示制御パネル。
"""

import logging
from typing import Dict, Union

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QAbstractItemView
)
from PySide6.QtCore import Qt, Signal

from core.analyzer.drawing_analyzer import LayerStats

logger = logging.getLogger(__name__)


class LayerPanel(QWidget):
    """
    レイヤー一覧および表示/非表示トグル管理パネル。
    
    Signals:
        layer_visibility_changed(layer_name: str, visible: bool)
    """

    layer_visibility_changed = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ヘッダータイトル
        self.title_label = QLabel("レイヤー一覧")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #7aa2f7;")
        layout.addWidget(self.title_label)

        # ツリーウィジェット
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["レイヤー名", "要素数"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree)

    def set_layers(self, layers: Dict[str, Union[LayerStats, int]]) -> None:
        """
        レイヤー情報の一覧を設定して更新する。
        
        Args:
            layers: レイヤー名をキー、LayerStats または要素数を値とする辞書
        """
        self.tree.blockSignals(True)
        self.tree.clear()

        for name, stats in sorted(layers.items()):
            count = stats.total if isinstance(stats, LayerStats) else stats
            item = QTreeWidgetItem(self.tree)
            item.setText(0, name)
            item.setText(1, str(count))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)

        self.tree.blockSignals(False)

    def clear(self) -> None:
        """表示内容をクリアする。"""
        self.tree.blockSignals(True)
        self.tree.clear()
        self.tree.blockSignals(False)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column == 0:
            layer_name = item.text(0)
            visible = (item.checkState(0) == Qt.CheckState.Checked)
            self.layer_visibility_changed.emit(layer_name, visible)
