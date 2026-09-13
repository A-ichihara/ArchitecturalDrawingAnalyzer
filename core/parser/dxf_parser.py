import os
import logging
from typing import Dict, Any, List, Optional

import ezdxf
from ezdxf.document import Drawing as EzdxfDrawing
from ezdxf.entities import (
    Line, LWPolyline, Polyline, Arc, Circle, Text, MText, Insert
)

from core.parser.interface import IDrawingParser
from core.models.drawing import (
    Drawing, DrawingElement, LineElement, PolylineElement,
    TextElement, CircleElement, ArcElement
)

logger = logging.getLogger(__name__)


class DxfParser(IDrawingParser):
    """
    ezdxfを使用してDXFファイルを解析し、共通 Drawing モデルへ変換するパーサー。
    
    対応エンティティ:
        LINE, LWPOLYLINE, POLYLINE, ARC, CIRCLE, TEXT, MTEXT
    """

    def parse(self, file_path: str, **kwargs) -> Drawing:
        """
        DXFファイルを読み込んで Drawing オブジェクトを返す。

        Args:
            file_path: DXFファイルのパス
            **kwargs: scale（縮尺逆数）, units（単位）
        Returns:
            Drawing オブジェクト
        Raises:
            なし（読み込み失敗時はログを出して空のDrawingを返す）
        """
        scale = kwargs.get("scale", 1.0)
        units = kwargs.get("units", "mm")
        drawing_id = os.path.splitext(os.path.basename(file_path))[0]

        try:
            doc = ezdxf.readfile(file_path)
        except ezdxf.DXFError as e:
            logger.error("DXF読み込みエラー: %s - %s", file_path, e)
            return Drawing(
                drawing_id=drawing_id,
                file_name=os.path.basename(file_path),
                file_type="dxf",
                scale=scale,
                units=units,
                elements=[],
            )
        except Exception as e:
            logger.error("予期しないエラー: %s - %s", file_path, e)
            return Drawing(
                drawing_id=drawing_id,
                file_name=os.path.basename(file_path),
                file_type="dxf",
                scale=scale,
                units=units,
                elements=[],
            )

        dxf_version = doc.dxfversion
        msp = doc.modelspace()

        logger.info("DXF読み込み完了: %s (version=%s)", file_path, dxf_version)

        elements: List[DrawingElement] = []
        unsupported_types: Dict[str, int] = {}
        element_counter = 0

        for entity in msp:
            try:
                elem = self._convert_entity(entity, element_counter)
                if elem is not None:
                    elements.append(elem)
                    element_counter += 1
                else:
                    etype = entity.dxftype()
                    unsupported_types[etype] = unsupported_types.get(etype, 0) + 1
            except Exception as e:
                logger.warning("エンティティ変換スキップ (%s): %s", entity.dxftype(), e)

        # ログ出力
        logger.info("取得要素数: %d", len(elements))
        if unsupported_types:
            logger.info("未対応エンティティ（スキップ）: %s", unsupported_types)

        drawing = Drawing(
            drawing_id=drawing_id,
            file_name=os.path.basename(file_path),
            file_type="dxf",
            scale=scale,
            units=units,
            elements=elements,
        )
        # DXFバージョンと未対応要素情報を properties に格納
        drawing_dict = {
            "dxf_version": dxf_version,
            "unsupported_types": unsupported_types,
        }
        # Drawingモデルに直接 properties はないため、
        # 解析メタデータは別属性として付加する
        drawing._meta = drawing_dict  # type: ignore[attr-defined]

        return drawing

    def get_layer_info(self, file_path: str) -> List[Dict[str, Any]]:
        """
        DXFファイルのレイヤー情報を取得する。
        
        Returns:
            [{"name": レイヤー名, "color": カラーコード, "is_on": 表示状態}, ...]
        """
        try:
            doc = ezdxf.readfile(file_path)
        except Exception as e:
            logger.error("レイヤー情報取得エラー: %s", e)
            return []

        layers = []
        for layer in doc.layers:
            layers.append({
                "name": layer.dxf.name,
                "color": layer.dxf.color,
                "is_on": layer.is_on(),
            })
        return layers

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _convert_entity(self, entity, index: int) -> Optional[DrawingElement]:
        """DXFエンティティを DrawingElement サブクラスへ変換する。"""
        etype = entity.dxftype()
        eid = f"{etype}_{index}"
        layer = entity.dxf.get("layer", "0")
        color = entity.dxf.get("color", None)

        if etype == "LINE":
            return self._convert_line(entity, eid, layer, color)
        elif etype == "LWPOLYLINE":
            return self._convert_lwpolyline(entity, eid, layer, color)
        elif etype == "POLYLINE":
            return self._convert_polyline(entity, eid, layer, color)
        elif etype == "ARC":
            return self._convert_arc(entity, eid, layer, color)
        elif etype == "CIRCLE":
            return self._convert_circle(entity, eid, layer, color)
        elif etype in ("TEXT", "ATTDEF", "ATTRIB"):
            return self._convert_text(entity, eid, layer, color)
        elif etype == "MTEXT":
            return self._convert_mtext(entity, eid, layer, color)
        else:
            return None

    def _convert_line(self, entity, eid, layer, color) -> LineElement:
        start = list(entity.dxf.start)[:2]
        end = list(entity.dxf.end)[:2]
        return LineElement(
            element_id=eid,
            element_type="LINE",
            layer=layer,
            color=color,
            start=start,
            end=end,
        )

    def _convert_lwpolyline(self, entity, eid, layer, color) -> PolylineElement:
        # LWPOLYLINEはXY座標のみ（Z=0）
        points = [[pt[0], pt[1]] for pt in entity.get_points("xy")]
        is_closed = bool(entity.closed)
        return PolylineElement(
            element_id=eid,
            element_type="POLYLINE",
            layer=layer,
            color=color,
            points=points,
            is_closed=is_closed,
        )

    def _convert_polyline(self, entity, eid, layer, color) -> PolylineElement:
        points = []
        try:
            for vertex in entity.vertices:
                pt = vertex.dxf.location
                points.append([float(pt.x), float(pt.y)])
        except Exception:
            pass
        is_closed = bool(entity.is_closed)
        return PolylineElement(
            element_id=eid,
            element_type="POLYLINE",
            layer=layer,
            color=color,
            points=points,
            is_closed=is_closed,
        )

    def _convert_arc(self, entity, eid, layer, color) -> ArcElement:
        center = list(entity.dxf.center)[:2]
        radius = float(entity.dxf.radius)
        start_angle = float(entity.dxf.start_angle)
        end_angle = float(entity.dxf.end_angle)
        return ArcElement(
            element_id=eid,
            element_type="ARC",
            layer=layer,
            color=color,
            center=center,
            radius=radius,
            start_angle=start_angle,
            end_angle=end_angle,
        )

    def _convert_circle(self, entity, eid, layer, color) -> CircleElement:
        center = list(entity.dxf.center)[:2]
        radius = float(entity.dxf.radius)
        return CircleElement(
            element_id=eid,
            element_type="CIRCLE",
            layer=layer,
            color=color,
            center=center,
            radius=radius,
        )

    def _convert_text(self, entity, eid, layer, color) -> TextElement:
        text = entity.dxf.get("text", "")
        insert = entity.dxf.get("insert", (0.0, 0.0))
        height = float(entity.dxf.get("height", 2.5))
        rotation = float(entity.dxf.get("rotation", 0.0))
        return TextElement(
            element_id=eid,
            element_type="TEXT",
            layer=layer,
            color=color,
            text=str(text),
            insertion_point=[float(insert[0]), float(insert[1])],
            height=height,
            rotation=rotation,
        )

    def _convert_mtext(self, entity, eid, layer, color) -> TextElement:
        text = ""
        if hasattr(entity, "plain_text"):
            text = entity.plain_text()
        elif hasattr(entity, "plain_mtext"):
            text = entity.plain_mtext()
        if not text and hasattr(entity, "text"):
            text = entity.text
        if not text and hasattr(entity, "dxf"):
            text = entity.dxf.get("text", "")

        insert = entity.dxf.get("insert", (0.0, 0.0))
        height = float(entity.dxf.get("char_height", 2.5))
        return TextElement(
            element_id=eid,
            element_type="TEXT",
            layer=layer,
            color=color,
            text=str(text),
            insertion_point=[float(insert[0]), float(insert[1])],
            height=height,
        )
