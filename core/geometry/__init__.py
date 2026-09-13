"""
core.geometry
Shapelyなどの幾何学演算エンジンをカプセル化し、共通インターフェースを提供します。
"""

from .engine import IGeometryEngine, ShapelyGeometryEngine

__all__ = ["IGeometryEngine", "ShapelyGeometryEngine"]
