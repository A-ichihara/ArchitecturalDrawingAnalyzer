"""
core.drawing_viewer
DXF/PDF図面を表示するためのQGraphicsView/Sceneベースのビューアコンポーネントを提供します。
将来的な解析結果レイヤーの追加（部屋境界・壁芯・差分マーキング等）に対応したレイヤー構造を持ちます。
"""

from .scene import DrawingScene
from .view import DrawingView
from .renderers import DxfRenderer

__all__ = ["DrawingScene", "DrawingView", "DxfRenderer"]
