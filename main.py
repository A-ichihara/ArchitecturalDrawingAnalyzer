"""
main.py
建築図面解析・設備設計支援システム エントリーポイント。

起動方法:
    python main.py
    # または
    dist/ArchitecturalDrawingAnalyzer.exe
"""

import sys
import logging
import os

# プロジェクトルートをPythonパスへ追加（EXE実行時にも対応）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ui.main_window import MainWindow


def setup_logging() -> None:
    """アプリケーション全体のロギングを設定する。"""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    # Windows上でEXE実行時にコンソールを非表示にする
    if sys.platform == "win32":
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)  # 0 = SW_HIDE
        except Exception:
            pass

    setup_logging()

    # High DPI 対応
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")


    app = QApplication(sys.argv)
    app.setApplicationName("建築図面解析・設備設計支援システム")
    app.setOrganizationName("ArchitecturalDrawingAnalyzer")
    app.setApplicationVersion("Phase1")

    # デフォルトフォント
    font = QFont("Yu Gothic UI", 10)
    app.setFont(font)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
