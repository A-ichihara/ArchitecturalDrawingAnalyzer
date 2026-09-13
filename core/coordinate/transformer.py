import numpy as np
from typing import List, Tuple, Union

class CoordinateTransformer:
    """
    CAD、PDF、画像などの異なる座標系と、共通座標系（現実世界のミリメートル、左下原点デカルト座標）
    との相互変換を行うクラス。
    3x3のアフィン変換行列を利用して、回転、反転、スケーリング、平行移動をサポートします。
    """
    def __init__(self, matrix: np.ndarray = None):
        """
        変換行列を指定して初期化します。指定がない場合は単位行列（変換なし）になります。
        """
        if matrix is None:
            self.matrix = np.eye(3)
        else:
            self.matrix = np.array(matrix, dtype=float)
            
        # 逆変換用の逆行列を計算してキャッシュ
        try:
            self.inv_matrix = np.linalg.inv(self.matrix)
        except np.linalg.LinAlgError:
            self.inv_matrix = np.eye(3)

    def transform(self, point: Union[List[float], Tuple[float, float]]) -> List[float]:
        """
        元の座標系（CAD/PDF/画像）から共通座標系（ミリメートル、左下原点）へ変換します。
        
        Args:
            point: [x, y] 座標
        Returns:
            [x_common, y_common] 座標
        """
        p = np.array([point[0], point[1], 1.0])
        res = self.matrix @ p
        return [float(res[0]), float(res[1])]

    def transform_list(self, points: List[List[float]]) -> List[List[float]]:
        """
        複数の座標リストを一括で共通座標系へ変換します。
        """
        return [self.transform(p) for p in points]

    def inverse_transform(self, point: Union[List[float], Tuple[float, float]]) -> List[float]:
        """
        共通座標系（ミリメートル、左下原点）から元の座標系（CAD/PDF/画像）へ逆変換します。
        
        Args:
            point: [x_common, y_common] 座標
        Returns:
            [x_orig, y_orig] 座標
        """
        p = np.array([point[0], point[1], 1.0])
        res = self.inv_matrix @ p
        return [float(res[0]), float(res[1])]

    def inverse_transform_list(self, points: List[List[float]]) -> List[List[float]]:
        """
        複数の共通座標リストを一括で元の座標系へ逆変換します。
        """
        return [self.inverse_transform(p) for p in points]

    @classmethod
    def from_cad(cls, scale: float = 1.0, offset_x: float = 0.0, offset_y: float = 0.0, units: str = "mm") -> 'CoordinateTransformer':
        """
        CAD座標系からの変換器を作成します。
        CADは基本的にデカルト座標（左下原点）です。
        
        Args:
            scale: 図面の縮尺の逆数 (例: 1/100図面の場合は 100 を指定して実サイズに変換する)
            offset_x: X軸方向の平行移動量 (ミリメートル単位)
            offset_y: Y軸方向の平行移動量 (ミリメートル単位)
            units: CADのデータ単位 ("mm" または "m")
        """
        # CAD単位のミリメートル換算
        unit_scale = 1.0
        if units == "m":
            unit_scale = 1000.0
            
        # 最終スケール = CAD単位スケール * 図面縮尺
        total_scale = unit_scale * scale
        
        matrix = np.array([
            [total_scale, 0.0, offset_x],
            [0.0, total_scale, offset_y],
            [0.0, 0.0, 1.0]
        ])
        return cls(matrix)

    @classmethod
    def from_pdf(cls, page_height_pt: float, scale: float = 1.0, dpi: float = 72.0, offset_x: float = 0.0, offset_y: float = 0.0, origin: str = "top_left") -> 'CoordinateTransformer':
        """
        PDF座標系（通常はポイント単位: 1pt = 1/72インチ）からの変換器を作成します。
        
        Args:
            page_height_pt: PDFページの高さ（ポイント単位）。Y軸反転処理に必要です。
            scale: 図面の縮尺の逆数 (例: 1/100図面の場合は 100)
            dpi: 解像度 (標準的なPDFは 72.0)
            offset_x: 平行移動量
            offset_y: 平行移動量
            origin: PDFの原点位置 ("top_left" または "bottom_left")
        """
        # 1ポイントあたりのミリメートル換算 (25.4 mm / 72.0 dpi = 0.352777... mm)
        pt_to_mm = 25.4 / dpi
        total_scale = pt_to_mm * scale
        
        if origin == "top_left":
            # PDFの左上原点を、共通座標系の左下原点へ変換（Y軸反転）
            # x_dest = x_src * total_scale + offset_x
            # y_dest = (page_height - y_src) * total_scale + offset_y
            #        = -y_src * total_scale + (page_height * total_scale) + offset_y
            matrix = np.array([
                [total_scale, 0.0, offset_x],
                [0.0, -total_scale, offset_y + (page_height_pt * total_scale)],
                [0.0, 0.0, 1.0]
            ])
        else:
            matrix = np.array([
                [total_scale, 0.0, offset_x],
                [0.0, total_scale, offset_y],
                [0.0, 0.0, 1.0]
            ])
        return cls(matrix)

    @classmethod
    def from_image(cls, dpi: float, scale: float = 1.0, image_height_px: float = 0.0, offset_x: float = 0.0, offset_y: float = 0.0) -> 'CoordinateTransformer':
        """
        画像座標系（ピクセル単位、左上原点）からの変換器を作成します。
        
        Args:
            dpi: 画像の解像度 (Dots Per Inch)
            scale: 図面の縮尺の逆数 (例: 1/100図面の場合は 100)
            image_height_px: 画像の縦幅（ピクセル単位）。Y軸反転に必要です。
            offset_x: 平行移動量
            offset_y: 平行移動量
        """
        # 1ピクセルあたりのミリメートル換算
        px_to_mm = 25.4 / dpi
        total_scale = px_to_mm * scale
        
        # 左上原点のピクセル座標から、左下原点の共通座標系へ変換（Y軸反転）
        matrix = np.array([
            [total_scale, 0.0, offset_x],
            [0.0, -total_scale, offset_y + (image_height_px * total_scale)],
            [0.0, 0.0, 1.0]
        ])
        return cls(matrix)
