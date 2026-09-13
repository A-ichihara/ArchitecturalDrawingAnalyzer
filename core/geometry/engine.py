from abc import ABC, abstractmethod
from typing import List, Tuple, Optional, Union
import math
from shapely.geometry import LineString, Polygon, Point
import shapely

class IGeometryEngine(ABC):
    """
    幾何計算エンジンのインターフェース。
    CAD要素やポリゴンなどの2D幾何計算を行う共通メソッドを定義します。
    """
    @abstractmethod
    def line_intersection(self, line_a: List[List[float]], line_b: List[List[float]]) -> List[List[float]]:
        """
        2つの線分の交点（複数ある場合は複数、ない場合は空リスト）を返します。
        線分は [[x_start, y_start], [x_end, y_end]] の形式。
        """
        pass

    @abstractmethod
    def line_distance(self, line_a: List[List[float]], line_b: List[List[float]]) -> float:
        """2つの線分の最短距離を返します。"""
        pass

    @abstractmethod
    def is_parallel(self, line_a: List[List[float]], line_b: List[List[float]], angle_tolerance_deg: float = 1.0) -> bool:
        """2つの線分が平行であるかを判定します（許容誤差考慮）。"""
        pass

    @abstractmethod
    def calculate_polygon_area(self, polygon_coords: List[List[float]]) -> float:
        """境界ポリゴンの面積を返します。"""
        pass

    @abstractmethod
    def polygon_buffer(self, polygon_coords: List[List[float]], distance: float) -> List[List[float]]:
        """ポリゴンを拡縮（バッファ処理）した新しいポリゴン座標を返します。"""
        pass

    @abstractmethod
    def intersects(self, geom_a: List[List[float]], geom_b: List[List[float]]) -> bool:
        """2つの幾何要素（ポリゴンやラインなど）が交差/重なっているかを判定します。"""
        pass

    @abstractmethod
    def compute_wall_centerline(self, line_a: List[List[float]], line_b: List[List[float]], distance_tolerance: float = 500.0, angle_tolerance_deg: float = 5.0) -> Optional[List[List[float]]]:
        """
        複線壁（2本の線分）から壁芯（1本の線分）を計算します。
        平行かつ距離が許容誤差内の場合、中間位置に壁芯を生成します。
        """
        pass

    @abstractmethod
    def extend_line(self, line: List[List[float]], distance: float) -> List[List[float]]:
        """線分の端点を指定距離だけ延長します。"""
        pass

    @abstractmethod
    def split_line(self, line: List[List[float]], split_point: List[float], tolerance: float = 1e-3) -> List[List[List[float]]]:
        """線分を指定座標で分割します。"""
        pass


class ShapelyGeometryEngine(IGeometryEngine):
    """
    Shapelyライブラリを利用した幾何計算エンジンの実装。
    """
    def line_intersection(self, line_a: List[List[float]], line_b: List[List[float]]) -> List[List[float]]:
        ls_a = LineString(line_a)
        ls_b = LineString(line_b)
        inter = ls_a.intersection(ls_b)
        
        if inter.is_empty:
            return []
        
        if isinstance(inter, Point):
            return [[inter.x, inter.y]]
            
        # 複数の交点、または重なり合っている場合
        if hasattr(inter, "geoms"):
            pts = []
            for g in inter.geoms:
                if isinstance(g, Point):
                    pts.append([g.x, g.y])
                elif isinstance(g, LineString):
                    pts.extend([[p[0], p[1]] for p in g.coords])
            # 重複を除く
            unique_pts = []
            for pt in pts:
                if pt not in unique_pts:
                    unique_pts.append(pt)
            return unique_pts
        elif isinstance(inter, LineString):
            return [[p[0], p[1]] for p in inter.coords]
            
        return []

    def line_distance(self, line_a: List[List[float]], line_b: List[List[float]]) -> float:
        ls_a = LineString(line_a)
        ls_b = LineString(line_b)
        return float(ls_a.distance(ls_b))

    def is_parallel(self, line_a: List[List[float]], line_b: List[List[float]], angle_tolerance_deg: float = 1.0) -> bool:
        # 2つの線分の方向ベクトルを計算
        dx_a = line_a[1][0] - line_a[0][0]
        dy_a = line_a[1][1] - line_a[0][1]
        dx_b = line_b[1][0] - line_b[0][0]
        dy_b = line_b[1][1] - line_b[0][1]
        
        # 傾きを求める
        angle_a = math.atan2(dy_a, dx_a)
        angle_b = math.atan2(dy_b, dx_b)
        
        # 角度差を計算 (ラジアン -> 度)
        diff = abs(angle_a - angle_b)
        diff_deg = math.degrees(diff) % 180.0
        
        # 180度（方向が逆なだけで平行）も考慮
        if diff_deg > 90.0:
            diff_deg = 180.0 - diff_deg
            
        return diff_deg <= angle_tolerance_deg

    def calculate_polygon_area(self, polygon_coords: List[List[float]]) -> float:
        if len(polygon_coords) < 3:
            return 0.0
            
        # ポリゴンが閉じていない場合は閉じる
        coords = list(polygon_coords)
        if coords[0] != coords[-1]:
            coords.append(coords[0])
            
        poly = Polygon(coords)
        return float(poly.area)

    def polygon_buffer(self, polygon_coords: List[List[float]], distance: float) -> List[List[float]]:
        if len(polygon_coords) < 3:
            return []
            
        coords = list(polygon_coords)
        if coords[0] != coords[-1]:
            coords.append(coords[0])
            
        poly = Polygon(coords)
        buffered = poly.buffer(distance)
        
        if buffered.is_empty:
            return []
            
        # 外周のみの座標を抽出
        if hasattr(buffered, "exterior") and buffered.exterior is not None:
            return [[p[0], p[1]] for p in buffered.exterior.coords]
            
        # マルチポリゴンの場合は最初の要素を返す
        if hasattr(buffered, "geoms") and len(buffered.geoms) > 0:
            first = buffered.geoms[0]
            if hasattr(first, "exterior") and first.exterior is not None:
                return [[p[0], p[1]] for p in first.exterior.coords]
                
        return []

    def intersects(self, geom_a: List[List[float]], geom_b: List[List[float]]) -> bool:
        def build_geom(coords):
            if len(coords) < 2:
                return Point(coords[0])
            elif len(coords) >= 3 and coords[0] == coords[-1]:
                return Polygon(coords)
            else:
                return LineString(coords)
                
        g_a = build_geom(geom_a)
        g_b = build_geom(geom_b)
        return bool(g_a.intersects(g_b))

    def compute_wall_centerline(self, line_a: List[List[float]], line_b: List[List[float]], distance_tolerance: float = 500.0, angle_tolerance_deg: float = 5.0) -> Optional[List[List[float]]]:
        # 1. 平行判定
        if not self.is_parallel(line_a, line_b, angle_tolerance_deg):
            return None
            
        # 2. 最短距離判定
        dist = self.line_distance(line_a, line_b)
        if dist > distance_tolerance:
            return None
            
        # 3. 中間線の計算
        # ベクトルの向きを揃える
        dx_a = line_a[1][0] - line_a[0][0]
        dy_a = line_a[1][1] - line_a[0][1]
        dx_b = line_b[1][0] - line_b[0][0]
        dy_b = line_b[1][1] - line_b[0][1]
        
        # 内積から同じ方向を向いているか判定、逆なら line_b の端点を入れ替える
        dot = dx_a * dx_b + dy_a * dy_b
        if dot < 0:
            line_b_oriented = [line_b[1], line_b[0]]
        else:
            line_b_oriented = line_b
            
        # 始点同士、終点同士の中間点を結ぶ線分を計算
        start_pt = [
            (line_a[0][0] + line_b_oriented[0][0]) / 2.0,
            (line_a[0][1] + line_b_oriented[0][1]) / 2.0
        ]
        end_pt = [
            (line_a[1][0] + line_b_oriented[1][0]) / 2.0,
            (line_a[1][1] + line_b_oriented[1][1]) / 2.0
        ]
        return [start_pt, end_pt]

    def extend_line(self, line: List[List[float]], distance: float) -> List[List[float]]:
        p1 = line[0]
        p2 = line[1]
        
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        length = math.sqrt(dx*dx + dy*dy)
        if length == 0:
            return line
            
        # 単位ベクトル
        ux = dx / length
        uy = dy / length
        
        # 双方を外側に延長
        new_p1 = [p1[0] - ux * distance, p1[1] - uy * distance]
        new_p2 = [p2[0] + ux * distance, p2[1] + uy * distance]
        return [new_p1, new_p2]

    def split_line(self, line: List[List[float]], split_point: List[float], tolerance: float = 1e-3) -> List[List[List[float]]]:
        ls = LineString(line)
        pt = Point(split_point)
        
        # 分割点と線分の距離が許容範囲外なら分割しない
        if ls.distance(pt) > tolerance:
            return [line]
            
        # 線分上の一番近い点を投影
        proj_dist = ls.project(pt)
        split_pt_on_line = ls.interpolate(proj_dist)
        split_coord = [split_pt_on_line.x, split_pt_on_line.y]
        
        # 分割点が端点に極めて近い場合は分割しない
        dist_to_start = math.sqrt((split_coord[0] - line[0][0])**2 + (split_coord[1] - line[0][1])**2)
        dist_to_end = math.sqrt((split_coord[0] - line[1][0])**2 + (split_coord[1] - line[1][1])**2)
        if dist_to_start < tolerance or dist_to_end < tolerance:
            return [line]
            
        return [
            [line[0], split_coord],
            [split_coord, line[1]]
        ]
