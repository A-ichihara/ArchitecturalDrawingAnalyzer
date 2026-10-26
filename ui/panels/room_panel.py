"""
ui.panels.room_panel
部屋候補の一覧と確認・修正のためのパネル。
一覧から部屋を選び、名前を編集したり、確定／却下／要確認の
状態を切り替えたりする。変更はシグナルで MainWindow へ通知する。
"""
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QLineEdit, QPushButton, QGroupBox, QComboBox,
)
from PySide6.QtCore import Qt, Signal

from core.drawing_viewer.room_overlay import display_area
from core.models.room import (
    REVIEW_STATUS_CONFIRMED,
    REVIEW_STATUS_LABELS,
    REVIEW_STATUS_REJECTED,
    REVIEW_STATUS_TO_CONFIRM,
    Room,
)


class RoomPanel(QWidget):
    """部屋候補の一覧表示と確認・修正パネル。"""

    room_selected = Signal(str)              # 部屋 ID
    room_name_changed = Signal(str, str)     # 部屋 ID, 新しい部屋名
    room_status_changed = Signal(str, str)   # 部屋 ID, 新しい確認状態
    area_basis_changed = Signal(str)         # 面積基準 ("inner" / "centerline")
    room_deleted = Signal(str)               # 部屋 ID

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rooms: Dict[str, Room] = {}
        self._current_room_id: Optional[str] = None
        self._area_basis = "inner"
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        title = QLabel("部屋候補")
        title.setStyleSheet("font-weight: bold; font-size: 13px; color: #7aa2f7;")
        layout.addWidget(title)

        # 面積基準の選択（壁芯は、壁芯面積がある部屋がある場合のみ選べる）。
        basis_row = QHBoxLayout()
        basis_row.addWidget(QLabel("面積基準"))
        self._basis_combo = QComboBox()
        self._basis_combo.addItem("内法", "inner")
        self._basis_combo.addItem("壁芯", "centerline")
        self._basis_combo.currentIndexChanged.connect(self._on_basis_changed)
        basis_row.addWidget(self._basis_combo)
        basis_row.addStretch()
        layout.addLayout(basis_row)

        self._room_list = QListWidget()
        self._room_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._room_list.currentItemChanged.connect(self._on_list_selection_changed)
        layout.addWidget(self._room_list)

        # 編集欄
        editor = QGroupBox("確認・修正")
        editor_layout = QVBoxLayout(editor)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("部屋名を入力")
        self._name_edit.editingFinished.connect(self._on_name_editing_finished)
        editor_layout.addWidget(QLabel("部屋名"))
        editor_layout.addWidget(self._name_edit)

        self._info_label = QLabel("部屋が選択されていません")
        self._info_label.setWordWrap(True)
        editor_layout.addWidget(self._info_label)

        buttons = QHBoxLayout()
        self._btn_confirm = QPushButton("確定")
        self._btn_confirm.clicked.connect(self._on_confirm_clicked)
        self._btn_reject = QPushButton("却下")
        self._btn_reject.clicked.connect(self._on_reject_clicked)
        self._btn_to_confirm = QPushButton("要確認に戻す")
        self._btn_to_confirm.clicked.connect(self._on_to_confirm_clicked)
        self._btn_delete = QPushButton("削除")
        self._btn_delete.clicked.connect(self._on_delete_clicked)
        buttons.addWidget(self._btn_confirm)
        buttons.addWidget(self._btn_reject)
        buttons.addWidget(self._btn_to_confirm)
        buttons.addWidget(self._btn_delete)
        editor_layout.addLayout(buttons)

        layout.addWidget(editor)
        self._set_editor_enabled(False)
        self.clear()

    # ------------------------------------------------------------------
    # 公開メソッド
    # ------------------------------------------------------------------

    def set_rooms(self, rooms: List[Room]) -> None:
        """部屋一覧を表示する。"""
        self._rooms = {room.room_id: room for room in rooms}
        self._current_room_id = None
        self._room_list.clear()
        for index, room in enumerate(sorted(rooms, key=lambda r: r.room_id), start=1):
            item = QListWidgetItem(self._room_item_text(index, room))
            item.setData(Qt.ItemDataRole.UserRole, room.room_id)
            self._room_list.addItem(item)
        self._set_editor_enabled(False)
        self._info_label.setText(f"部屋候補：{len(rooms)} 件")
        self._update_basis_availability()

    @property
    def area_basis(self) -> str:
        """現在選択されている面積基準 ("inner" / "centerline")。"""
        return self._area_basis

    def set_area_basis(self, basis: str) -> None:
        """面積基準を切り替え、一覧表示を更新する。"""
        if basis not in ("inner", "centerline"):
            return
        if basis == "centerline" and not self._has_centerline_area():
            basis = "inner"
        if basis == self._area_basis:
            return
        self._area_basis = basis
        index = self._basis_combo.findData(basis)
        if index >= 0:
            self._basis_combo.blockSignals(True)
            self._basis_combo.setCurrentIndex(index)
            self._basis_combo.blockSignals(False)
        self._refresh_list()
        self.area_basis_changed.emit(basis)

    def _has_centerline_area(self) -> bool:
        return any(
            room.properties.get("area_centerline_m2") is not None
            for room in self._rooms.values()
        )

    def _update_basis_availability(self) -> None:
        """壁芯面積がある部屋がない場合、壁芯の選択肢を無効化する。"""
        available = self._has_centerline_area()
        item = self._basis_combo.model().item(1)
        if item is not None:
            item.setEnabled(available)
        if not available and self._area_basis == "centerline":
            self._area_basis = "inner"
            self._basis_combo.blockSignals(True)
            self._basis_combo.setCurrentIndex(0)
            self._basis_combo.blockSignals(False)

    def _refresh_list(self) -> None:
        """一覧の表示を現在の部屋情報と面積基準で更新する。"""
        for row in range(self._room_list.count()):
            item = self._room_list.item(row)
            room = self._rooms.get(item.data(Qt.ItemDataRole.UserRole))
            if room is not None:
                item.setText(self._room_item_text(row + 1, room))

    def delete_room(self, room_id: str) -> bool:
        """指定した部屋を一覧から削除する。削除した場合は True を返す。"""
        room = self._rooms.pop(room_id, None)
        if room is None:
            return False
        for row in range(self._room_list.count()):
            item = self._room_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == room_id:
                self._room_list.takeItem(row)
                break
        if self._current_room_id == room_id:
            self._current_room_id = None
            self._name_edit.clear()
            self._info_label.setText(f"部屋候補：{len(self._rooms)} 件")
            self._set_editor_enabled(False)
        self._refresh_list()
        self._update_basis_availability()
        return True

    def select_room(self, room_id: str) -> None:
        """指定した部屋を一覧で選択し、編集欄に表示する。"""
        for row in range(self._room_list.count()):
            item = self._room_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == room_id:
                self._room_list.setCurrentItem(item)
                return

    def show_room(self, room: Room) -> None:
        """指定した部屋を編集欄に表示する。"""
        self._current_room_id = room.room_id
        self._name_edit.setText(room.room_name)
        self._info_label.setText(self._room_info_text(room))
        self._set_editor_enabled(True)

    def clear(self) -> None:
        """一覧と編集欄をクリアする。"""
        self._rooms = {}
        self._current_room_id = None
        self._room_list.clear()
        self._name_edit.clear()
        self._info_label.setText("部屋候補はまだ検出されていません")
        self._set_editor_enabled(False)

    # ------------------------------------------------------------------
    # 内部処理
    # ------------------------------------------------------------------

    def _room_item_text(self, index: int, room: Room) -> str:
        name = room.room_name or "（未判定）"
        status = REVIEW_STATUS_LABELS.get(room.review_status, "要確認")
        area, basis = display_area(room, self._area_basis)
        suffix = "（壁芯）" if basis == "centerline" else ""
        return f"{index}. {name} — {area:.2f} m²{suffix} [{status}]"

    def _room_info_text(self, room: Room) -> str:
        status = REVIEW_STATUS_LABELS.get(room.review_status, "要確認")
        candidate = room.properties.get("candidate_type", "unknown")
        area, basis = display_area(room, self._area_basis)
        basis_label = "壁芯" if basis == "centerline" else "内法"
        return (
            f"面積：{area:.2f} m²（{basis_label}）\n"
            f"状態：{status}\n"
            f"候補種別：{candidate}\n"
            f"確信度：{room.confidence:.2f}"
        )

    def _set_editor_enabled(self, enabled: bool) -> None:
        self._name_edit.setEnabled(enabled)
        self._btn_confirm.setEnabled(enabled)
        self._btn_reject.setEnabled(enabled)
        self._btn_to_confirm.setEnabled(enabled)
        self._btn_delete.setEnabled(enabled)

    def _refresh_list_item(self, room_id: str) -> None:
        """一覧の表示を最新の部屋情報で更新する。"""
        room = self._rooms.get(room_id)
        if room is None:
            return
        for row in range(self._room_list.count()):
            item = self._room_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == room_id:
                item.setText(self._room_item_text(row + 1, room))
                return

    def _on_basis_changed(self, _index: int) -> None:
        basis = self._basis_combo.currentData()
        if basis not in ("inner", "centerline") or basis == self._area_basis:
            return
        self._area_basis = basis
        self._refresh_list()
        self.area_basis_changed.emit(basis)

    def _on_list_selection_changed(self, current, _previous) -> None:
        if current is None:
            return
        room_id = current.data(Qt.ItemDataRole.UserRole)
        room = self._rooms.get(room_id)
        if room is None:
            return
        self.show_room(room)
        self.room_selected.emit(room_id)

    def _on_name_editing_finished(self) -> None:
        if self._current_room_id is None:
            return
        room = self._rooms.get(self._current_room_id)
        if room is None:
            return
        new_name = self._name_edit.text().strip()
        if new_name == room.room_name:
            return
        room.room_name = new_name
        self._refresh_list_item(room.room_id)
        self.room_name_changed.emit(room.room_id, new_name)

    def _change_status(self, status: str) -> None:
        if self._current_room_id is None:
            return
        room = self._rooms.get(self._current_room_id)
        if room is None:
            return
        if room.review_status == status:
            return
        room.review_status = status
        self._refresh_list_item(room.room_id)
        self._info_label.setText(self._room_info_text(room))
        self.room_status_changed.emit(room.room_id, status)

    def _on_confirm_clicked(self) -> None:
        self._change_status(REVIEW_STATUS_CONFIRMED)

    def _on_reject_clicked(self) -> None:
        self._change_status(REVIEW_STATUS_REJECTED)

    def _on_to_confirm_clicked(self) -> None:
        self._change_status(REVIEW_STATUS_TO_CONFIRM)

    def _on_delete_clicked(self) -> None:
        if self._current_room_id is None:
            return
        room_id = self._current_room_id
        if self.delete_room(room_id):
            self.room_deleted.emit(room_id)
