import pytest
import math
from core.geometry.engine import ShapelyGeometryEngine

def test_line_intersection():
    engine = ShapelyGeometryEngine()
    
    # 交差する2本の線分
    line_a = [[0.0, 0.0], [100.0, 100.0]]
    line_b = [[0.0, 100.0], [100.0, 0.0]]
    pts = engine.line_intersection(line_a, line_b)
    assert len(pts) == 1
    assert pts[0] == [50.0, 50.0]
    
    # 交差しない平行な線分
    line_c = [[0.0, 10.0], [100.0, 110.0]]
    pts_none = engine.line_intersection(line_a, line_c)
    assert len(pts_none) == 0

def test_line_distance():
    engine = ShapelyGeometryEngine()
    
    # 平行線間の距離
    line_a = [[0.0, 0.0], [1000.0, 0.0]]
    line_b = [[0.0, 200.0], [1000.0, 200.0]]
    assert engine.line_distance(line_a, line_b) == 200.0

def test_is_parallel():
    engine = ShapelyGeometryEngine()
    
    line_a = [[0.0, 0.0], [100.0, 0.0]]
    line_b = [[0.0, 200.0], [500.0, 200.0]]  # 完全平行
    line_c = [[0.0, 0.0], [100.0, 2.0]]      # わずかに傾いている (約1.14度)
    
    assert engine.is_parallel(line_a, line_b) is True
    # デフォルトの許容誤差 1.0 度を下回る傾きのため False
    assert engine.is_parallel(line_a, line_c, angle_tolerance_deg=1.0) is False
    # 許容誤差を 2.0 度にすれば True
    assert engine.is_parallel(line_a, line_c, angle_tolerance_deg=2.0) is True

def test_calculate_polygon_area():
    engine = ShapelyGeometryEngine()
    
    # 5000mm x 5000mm = 25m2 = 25,000,000 mm2 の正方形
    poly = [[0.0, 0.0], [5000.0, 0.0], [5000.0, 5000.0], [0.0, 5000.0]]
    area = engine.calculate_polygon_area(poly)
    assert area == 25000000.0

def test_polygon_buffer():
    engine = ShapelyGeometryEngine()
    
    # 10m x 10m の正方形
    poly = [[0.0, 0.0], [10000.0, 0.0], [10000.0, 10000.0], [0.0, 10000.0]]
    # 外側に 500mm 拡大
    buffered = engine.polygon_buffer(poly, 500.0)
    assert len(buffered) > 0
    
    # 拡大されたので面積は元の 100,000,000 mm2 より大きくなる
    original_area = engine.calculate_polygon_area(poly)
    buffered_area = engine.calculate_polygon_area(buffered)
    assert buffered_area > original_area

def test_compute_wall_centerline():
    engine = ShapelyGeometryEngine()
    
    # 複線壁（平行、距離 200mm）
    line_a = [[0.0, 0.0], [5000.0, 0.0]]
    line_b = [[0.0, 200.0], [5000.0, 200.0]]
    
    # 壁芯は y = 100 になるはず
    center = engine.compute_wall_centerline(line_a, line_b, distance_tolerance=300.0)
    assert center is not None
    assert center == [[0.0, 100.0], [5000.0, 100.0]]
    
    # 逆向きの複線壁ペア (端点の向きが逆)
    line_b_rev = [[5000.0, 200.0], [0.0, 200.0]]
    center_rev = engine.compute_wall_centerline(line_a, line_b_rev, distance_tolerance=300.0)
    assert center_rev is not None
    # 内部でベクトル方向が補正され、壁芯が正しく求められる
    assert center_rev == [[0.0, 100.0], [5000.0, 100.0]]

def test_extend_line():
    engine = ShapelyGeometryEngine()
    
    # 長さ100のX軸方向の線分
    line = [[10.0, 10.0], [110.0, 10.0]]
    # 両端をそれぞれ 10 ずつ延長 -> [[0.0, 10.0], [120.0, 10.0]]
    extended = engine.extend_line(line, 10.0)
    assert extended == [[0.0, 10.0], [120.0, 10.0]]

def test_split_line():
    engine = ShapelyGeometryEngine()
    
    line = [[0.0, 0.0], [1000.0, 0.0]]
    # 中間点 (500, 0) で分割
    parts = engine.split_line(line, [500.0, 0.0])
    assert len(parts) == 2
    assert parts[0] == [[0.0, 0.0], [500.0, 0.0]]
    assert parts[1] == [[500.0, 0.0], [1000.0, 0.0]]
    
    # 線上にない点で分割を試みる -> 分割されず元の線分がそのまま返る
    parts_no = engine.split_line(line, [500.0, 50.0])
    assert len(parts_no) == 1
    assert parts_no[0] == line
