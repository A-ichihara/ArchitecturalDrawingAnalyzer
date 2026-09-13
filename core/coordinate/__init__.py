"""
core.coordinate
CAD、PDF、画像などの異なる座標系を相互に変換する機能を提供します。
"""

from .transformer import CoordinateTransformer

__all__ = ["CoordinateTransformer"]
