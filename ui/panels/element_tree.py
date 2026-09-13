"""
ui.panels.element_tree
図面内の全要素を レイヤー → 種別 → 要素ID のツリー構造で表示・選択するパネル。
"""

import logging
from typing import Optional, Dict, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt, Signal

from core.models.drawing import Drawing, DrawingElement

logger = logging.getLogger(__name__)

# アイテムのデータ役割
ROLE_ELEMENT_ID = Qt.ItemDataRole.UserRole + 1


class ElementTreePanel(QWidget):
    """
    要素ツリー表示・選択パネル。
    
    Signals:
        element_selected(element_id: str)
    """

    element_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # タイトル
        self.title_label = QLabel("要素ツリー")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #7aa2f7;")
        layout.addWidget(self.title_label)

        # ツリー
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["要素構造"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.tree)

    def set_drawing(self, drawing: Optional[Drawing]) -> None:
        """
        Drawing オブジェクトからツリーノードを構築する。
        
        Args:
            drawing: 構造化データ（Noneの場合はクリア）
        """
        self.tree.blockSignals(True)
        self.tree.clear()

        if drawing is None or not drawing.elements:
            self.tree.blockSignals(False)
            return

        # レイヤー → 種別 → 要素リスト のマップを構築
        tree_map: Dict[str, Dict[str, List[DrawingElement]]] = {}
        for elem in drawing.elements:
            layer = elem.layer or "0"
            etype = elem.element_type
            if layer not in tree_map:
                tree_map[layer] = {}
            if etype not in tree_map[layer]:
                tree_map[layer][etype] = []
            tree_map[layer][etype].append(elem)

        # ツリー構築
        for layer_name in sorted(tree_map.keys()):
            layer_item = QTreeWidgetItem(self.tree)
            layer_item.setText(0, f"Layer: {layer_name}")

            for etype in sorted(tree_map[layer_name].keys()):
                elems = tree_map[layer_name][etype]
                type_item = QTreeWidgetItem(layer_item)
                type_item.setText(0, f"{etype} ({len(elems)})")

                for elem in elems:
                    elem_item = QTreeWidgetItem(type_item)
                    label = f"{elem.element_id}"
                    if hasattr(elem, "text") and getattr(elem, "text"):
                        label += f" (\"{getattr(elem, 'text')}\")"
                    elif hasattr(elem, "block_name") and getattr(elem, "block_name"):
                        label += f" [{getattr(elem, 'block_name')}]"

                    elem_item.setText(0, label)
                    elem_item.setData(0, ROLE_ELEMENT_ID, elem.element_id)

        self.tree.blockSignals(False)

    def clear(self) -> None:
        """ツリーをクリアする。"""
        self.tree.blockSignals(True)
        self.tree.clear()
        self.tree.blockSignals(False)

    def _on_selection_changed(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            return
        item = items[0]
        element_id = item.data(0, ROLE_ELEMENT_ID)
        if element_id:
            self.element_selected.emit(element_id)
