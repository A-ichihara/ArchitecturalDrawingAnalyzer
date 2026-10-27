"""図面単位と面積換算の共有定義。

room_detector と wall_detector の両方から使うため、循環参照を避けて
ここに置く。値は単位の二乗を m² へ換算する係数。
"""
from __future__ import annotations

_AREA_TO_M2 = {
    "mm": 1e-6,
    "millimeter": 1e-6,
    "millimeters": 1e-6,
    "cm": 1e-4,
    "centimeter": 1e-4,
    "centimeters": 1e-4,
    "m": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "in": 0.0254**2,
    "inch": 0.0254**2,
    "inches": 0.0254**2,
    "ft": 0.3048**2,
    "foot": 0.3048**2,
    "feet": 0.3048**2,
}
