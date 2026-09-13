"""
ui.panels.property_panel
選択された図面要素の詳細プロパティ表示パネル。
"""

import logging
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt

from core.models.drawing import (
    DrawingElement, LineElement, PolylineElement, ArcElement,
    CircleElement, TextElement, InsertElement
)

logger = logging.getLogger(__name__)


class PropertyPanel(QWidget):
    """
    選択要素の属性・幾何情報を表示するプロパティパネル。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # タイトル
        self.title_label = QLabel("プロパティ")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #7aa2f7;")
        layout.addWidget(self.title_label)

        # プロパティテーブル
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["プロパティ", "値"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        layout.addWidget(self.table)
        self.clear()

    def clear(self) -> None:
        """表示をクリアする。"""
        self.table.setRowCount(0)
        self._add_row("ステータス", "要素が選択されていません")

    def show_element(self, element: Optional[DrawingElement]) -> None:
        """
        選択された要素の情報テーブルを表示する。
        
        Args:
            element: 表示対象の DrawingElement（Noneの場合はクリア）
        """
        if element is None:
            self.clear()
            return

        self.table.setRowCount(0)

        # 1. 共通プロパティ
        self._add_row("要素ID", str(element.element_id))
        self._add_row("種別", str(element.element_type))
        self._add_row("レイヤー", str(element.layer or "0"))
        self._add_row("カラーコード", str(element.color if element.color is not None else "ByLayer"))

        # 2. 要素別プロパティ
        if isinstance(element, LineElement):
            self._add_row("始点", f"({element.start[0]:.2f}, {element.start[1]:.2f})")
            self._add_row("終点", f"({element.end[0]:.2f}, {element.end[1]:.2f})")
            self._add_row("長さ", f"{element.length:.2f} mm")
            self._add_row("角度", f"{element.angle:.2f}°")

        elif isinstance(element, PolylineElement):
            self._add_row("頂点数", str(element.vertex_count))
            self._add_row("閉路", "はい" if element.is_closed else "いいえ")
            self._add_row("全長", f"{element.length:.2f} mm")

        elif isinstance(element, ArcElement):
            self._add_row("中心点", f"({element.center[0]:.2f}, {element.center[1]:.2f})")
            self._add_row("半径", f"{element.radius:.2f} mm")
            self._add_row("開始角", f"{element.start_angle:.2f}°")
            self._add_row("終了角", f"{element.end_angle:.2f}°")
            self._add_row("中心角", f"{element.span_angle:.2f}°")
            self._add_row("弧長", f"{element.arc_length:.2f} mm")

        elif isinstance(element, CircleElement):
            self._add_row("中心点", f"({element.center[0]:.2f}, {element.center[1]:.2f})")
            self._add_row("半径", f"{element.radius:.2f} mm")
            self._add_row("直径", f"{element.diameter:.2f} mm")
            self._add_row("周長", f"{element.circumference:.2f} mm")
            self._add_row("面積", f"{element.area:.2f} mm²")

        elif isinstance(element, TextElement):
            self._add_row("文字列", element.text)
            self._add_row("高さ", f"{element.height:.2f} mm")
            self._add_row("回転角", f"{element.rotation:.2f}°")
            self._add_row("挿入点", f"({element.insertion_point[0]:.2f}, {element.insertion_point[1]:.2f})")
            if element.style:
                self._add_row("スタイル", element.style)

        elif isinstance(element, InsertElement):
            self._add_row("ブロック名", element.block_name)
            self._add_row("挿入点", f"({element.insert_point[0]:.2f}, {element.insert_point[1]:.2f})")
            self._add_row("回転角", f"{element.rotation:.2f}°")
            self._add_row("スケール (X, Y, Z)", f"({element.scale_x:.2f}, {element.scale_y:.2f}, {element.scale_z:.2f})")

    def _add_row(self, key: str, value: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        item_key = QTableWidgetItem(key)
        item_val = QTableWidgetItem(value)
        
        item_key.setFlags(item_key.flags() ^ Qt.ItemFlag.ItemIsEditable)
        item_val.setFlags(item_val.flags() ^ Qt.ItemFlag.ItemIsEditable)
        
        self.table.setItem(row, 0, item_key)
        self.table.setItem(row, 1, item_val)
