"""
tests.test_element_geometry
DrawingElement サブクラスにおける各幾何プロパティ（長さ・角度・面積・周長等）の決定論的計算精度の単体テスト。
"""

import math
import pytest

from core.models.drawing import (
    LineElement, PolylineElement, ArcElement,
    CircleElement, TextElement, InsertElement
)


def test_line_geometry():
    # 水平線 (長さ100, 角度0°)
    line_h = LineElement(element_id="LINE_000001", element_type="LINE", layer="0", start=(0.0, 0.0), end=(100.0, 0.0))
    assert pytest.approx(line_h.length, abs=1e-6) == 100.0
    assert pytest.approx(line_h.angle, abs=1e-6) == 0.0

    # 垂直線 (長さ50, 角度90°)
    line_v = LineElement(element_id="LINE_000002", element_type="LINE", layer="0", start=(0.0, 0.0), end=(0.0, 50.0))
    assert pytest.approx(line_v.length, abs=1e-6) == 50.0
    assert pytest.approx(line_v.angle, abs=1e-6) == 90.0

    # 斜め 45° (長さ10√2)
    line_d = LineElement(element_id="LINE_000003", element_type="LINE", layer="0", start=(0.0, 0.0), end=(10.0, 10.0))
    assert pytest.approx(line_d.length, abs=1e-6) == math.sqrt(200.0)
    assert pytest.approx(line_d.angle, abs=1e-6) == 45.0


def test_polyline_geometry():
    # 開いたポリライン (0,0) -> (10,0) -> (10,20)
    poly_open = PolylineElement(
        element_id="POLY_000001", element_type="POLYLINE", layer="0",
        points=[(0.0, 0.0), (10.0, 0.0), (10.0, 20.0)],
        is_closed=False
    )
    assert poly_open.vertex_count == 3
    assert pytest.approx(poly_open.length, abs=1e-6) == 30.0

    # 閉じたポリライン (幅100 x 高さ50 の長方形)
    poly_closed = PolylineElement(
        element_id="POLY_000002", element_type="POLYLINE", layer="0",
        points=[(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)],
        is_closed=True
    )
    assert poly_closed.vertex_count == 4
    # 周長 100 + 50 + 100 + 50 = 300
    assert pytest.approx(poly_closed.length, abs=1e-6) == 300.0


def test_arc_geometry():
    # 90度の円弧 (半径 100, 0° -> 90°)
    arc = ArcElement(
        element_id="ARC_000001", element_type="ARC", layer="0",
        center=(0.0, 0.0), radius=100.0,
        start_angle=0.0, end_angle=90.0
    )
    assert pytest.approx(arc.span_angle, abs=1e-6) == 90.0
    # 弧長 = 2 * π * 100 * (90/360) = 50 * π
    assert pytest.approx(arc.arc_length, abs=1e-6) == 50.0 * math.pi

    # 350° から 20° への跨ぎ円弧 (中心角 30°)
    arc_wrap = ArcElement(
        element_id="ARC_000002", element_type="ARC", layer="0",
        center=(0.0, 0.0), radius=10.0,
        start_angle=350.0, end_angle=20.0
    )
    assert pytest.approx(arc_wrap.span_angle, abs=1e-6) == 30.0


def test_circle_geometry():
    # 半径 10 の円
    circle = CircleElement(
        element_id="CIRC_000001", element_type="CIRCLE", layer="0",
        center=(0.0, 0.0), radius=10.0
    )
    assert pytest.approx(circle.diameter, abs=1e-6) == 20.0
    assert pytest.approx(circle.circumference, abs=1e-6) == 20.0 * math.pi
    assert pytest.approx(circle.area, abs=1e-6) == 100.0 * math.pi


def test_text_element():
    text = TextElement(
        element_id="TEXT_000001", element_type="TEXT", layer="ANNOTATION",
        text="主寝室", height=250.0, rotation=0.0,
        insertion_point=(1000.0, 2000.0), style="Standard"
    )
    assert text.element_type == "TEXT"
    assert text.text == "主寝室"
    assert text.style == "Standard"


def test_insert_element():
    insert = InsertElement(
        element_id="INST_000001", element_type="INSERT", layer="EQUIPMENT",
        block_name="DOOR_800", insert_point=(500.0, 1000.0),
        rotation=90.0, scale_x=1.0, scale_y=1.0, scale_z=1.0
    )
    assert insert.element_type == "INSERT"
    assert insert.block_name == "DOOR_800"
    assert insert.insert_point == (500.0, 1000.0)
    assert insert.rotation == 90.0

