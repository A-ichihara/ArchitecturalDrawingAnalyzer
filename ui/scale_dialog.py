"""
ui.scale_dialog
PDF を開くときに mm/pt 換算率を尋ねるダイアログ。

PDF には実寸への換算率が含まれていないため、ユーザーに入力して
もらう。換算率が分からない場合は空欄のまま開くことができ、その
場合は 1pt=1mm として読み込み、後から寸法に合わせて倍率調整する。
"""
from typing import Optional, Tuple

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

# ダイアログで「キャンセル」が選ばれたことを表す目印。
SCALE_DIALOG_CANCELLED = object()


class PdfScaleDialog(QDialog):
    """PDF の換算率（mm/pt）を尋ねるダイアログ。"""

    def __init__(self, parent=None, file_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("PDF の換算率を入力")
        self._value: Optional[float] = None
        self._build_ui(file_name)

    def _build_ui(self, file_name: str) -> None:
        layout = QVBoxLayout(self)

        title = QLabel(f"PDF を開きます: {file_name}" if file_name else "PDF を開きます")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        explanation = QLabel(
            "PDF には実寸への換算率が含まれていません。\n"
            "1pt あたりの mm 数を入力してください。\n"
            "換算率が分からない場合は空欄のまま開けます。\n"
            "開いた後、寸法に合わせて調整できます。"
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        hint = QLabel(
            "考え方：換算率は、図面の寸法値と PDF 上での長さの比で決まります。\n"
            "例えば寸法 4000mm の線が PDF 上で 400pt なら、4000 ÷ 400 = 10mm/pt です。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #a9b1d6;")
        layout.addWidget(hint)

        self._input = QLineEdit()
        self._input.setPlaceholderText("例：10")
        self._input.setToolTip("1pt あたりの mm 数（空欄の場合は未指定）")
        layout.addWidget(self._input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def scale_mm_per_pt(self) -> Optional[float]:
        """入力された換算率を返す。空欄の場合は None（未指定）。"""
        return self._value

    def accept(self) -> None:
        value, error = self.parse_scale_text(self._input.text())
        if error is not None:
            QMessageBox.warning(self, "換算率の入力", error)
            return
        self._value = value
        super().accept()

    @staticmethod
    def parse_scale_text(text: str) -> Tuple[Optional[float], Optional[str]]:
        """換算率の入力文字列を検証する。

        空欄なら (None, None)（未指定）。数値として読めない、または
        0 以下の場合は (None, エラーメッセージ) を返す。
        """
        cleaned = (text or "").strip()
        if not cleaned:
            return None, None
        try:
            value = float(cleaned)
        except ValueError:
            return None, "数値を入力してください（例：10）。\n空欄のままでも開けます。"
        if value <= 0:
            return None, "換算率は 0 より大きい数値を入力してください。\n空欄のままでも開けます。"
        return value, None
