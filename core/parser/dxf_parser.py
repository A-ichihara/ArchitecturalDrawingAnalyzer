import math
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
    TextElement, CircleElement, ArcElement, InsertElement
)

logger = logging.getLogger(__name__)

# 単位あたりのメートル換算（長さ）。図面の外形寸法が建築図面として
# 不自然に大きくなる場合に、単位宣言の誤りを疑うための目安に使う。
_LINEAR_METRES_PER_UNIT = {
    "mm": 0.001,
    "millimeter": 0.001,
    "millimeters": 0.001,
    "cm": 0.01,
    "centimeter": 0.01,
    "centimeters": 0.01,
    "m": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "in": 0.0254,
    "inch": 0.0254,
    "inches": 0.0254,
    "ft": 0.3048,
    "foot": 0.3048,
    "feet": 0.3048,
}

# 建築図面として不自然に大きいとみなす外形寸法（メートル）。
# これを超える図面は、単位宣言が座標の桁数と食い違っている可能性が高い。
# 例：mm単位の座標に $INSUNITS=メートルが付いた図面は 1000 m を軽く超える。
_MAX_PLAUSIBLE_DRAWING_SIZE_M = 1000.0


# ブロック展開の深さ上限。自己参照ブロックなどによる無限再帰を防ぐ。
_MAX_BLOCK_EXPANSION_DEPTH = 10


def _compose_transform(outer, inner):
    """Compose two 2D affine transforms, each (a, b, c, d, tx, ty).

    A point maps as x' = a*x + b*y + tx, y' = c*x + d*y + ty.
    The result applies `inner` first, then `outer`.
    """
    ao, bo, co, do, to_x, to_y = outer
    ai, bi, ci, di, ti_x, ti_y = inner
    return (
        ao * ai + bo * ci,
        ao * bi + bo * di,
        co * ai + do * ci,
        co * bi + do * di,
        ao * ti_x + bo * ti_y + to_x,
        co * ti_x + do * ti_y + to_y,
    )


def _transform_point(transform, point):
    """Apply a 2D affine transform to an (x, y) point."""
    a, b, c, d, tx, ty = transform
    x, y = float(point[0]), float(point[1])
    return [a * x + b * y + tx, c * x + d * y + ty]


def _transform_angle(transform, angle_deg):
    """Transform a direction angle through a 2D affine map.

    Using direction vectors (instead of adding a rotation) keeps the
    result correct for mirrored transforms as well.
    """
    a, b, c, d, _tx, _ty = transform
    theta = math.radians(float(angle_deg))
    dx = a * math.cos(theta) + b * math.sin(theta)
    dy = c * math.cos(theta) + d * math.sin(theta)
    return math.degrees(math.atan2(dy, dx)) % 360.0


def _uniform_scale(transform):
    """Return the uniform scale factor of a 2D affine map, or None.

    Circles and arcs cannot be represented after a non-uniform scale
    (they become ellipses), so those entities are skipped in that case.
    """
    a, b, c, d, _tx, _ty = transform
    col_x = math.hypot(a, c)
    col_y = math.hypot(b, d)
    if col_x == 0.0 or col_y == 0.0:
        return None
    if not math.isclose(col_x, col_y, rel_tol=1e-9, abs_tol=0.0):
        return None
    if abs(a * b + c * d) > 1e-9 * col_x * col_y:
        return None
    return col_x


def _check_unit_plausibility(
    elements: List[DrawingElement], units: str, units_source: str
) -> str | None:
    """宣言単位と座標の桁数の食い違いを検出し、警告文を返す。

    単位が未設定で mm にフォールバックした場合（units_source == "default_mm"）
    は、宣言自体がないため警告しない。座標が得られない場合も警告しない。
    警告はあくまで疑いであり、読み込みや面積計算の動作は変えない。
    """
    if units_source == "default_mm":
        return None
    factor = _LINEAR_METRES_PER_UNIT.get((units or "").strip().lower())
    if factor is None:
        return None

    points: List[tuple] = []
    for elem in elements:
        try:
            if isinstance(elem, LineElement):
                points.extend([tuple(elem.start[:2]), tuple(elem.end[:2])])
            elif isinstance(elem, PolylineElement):
                points.extend([tuple(pt[:2]) for pt in elem.points])
            elif isinstance(elem, TextElement):
                points.append(tuple(elem.insertion_point[:2]))
            elif isinstance(elem, (CircleElement, ArcElement)):
                cx, cy = float(elem.center[0]), float(elem.center[1])
                r = float(elem.radius)
                points.extend([(cx - r, cy - r), (cx + r, cy + r)])
            elif isinstance(elem, InsertElement):
                points.append(tuple(elem.insert_point[:2]))
        except (TypeError, ValueError, IndexError, OverflowError):
            continue
    if not points:
        return None
    try:
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
    except (TypeError, ValueError, OverflowError):
        return None
    max_size_m = max(max(xs) - min(xs), max(ys) - min(ys)) * factor
    if max_size_m <= _MAX_PLAUSIBLE_DRAWING_SIZE_M:
        return None
    return (
        f"図面の外形が約 {max_size_m:,.0f} m あり、建築図面として不自然に大きいため、"
        f"単位設定を確認してください（宣言単位: {units}）。座標が mm 単位で記録され、"
        f"単位宣言がメートル等になっている場合、面積が大幅に誤ります。"
    )


class DxfParser(IDrawingParser):
    """
    ezdxfを使用してDXFファイルを解析し、共通 Drawing モデルへ変換するパーサー。

    対応エンティティ:
        LINE, LWPOLYLINE, POLYLINE, ARC, CIRCLE, TEXT, MTEXT, INSERT
    INSERT（ブロック参照）はブロック定義を展開し、挿入位置・回転・倍率を
    適用した図形要素に変換する。展開できない参照（未定義ブロック等）は
    InsertElement として残し、ビューアではマーカー表示される。
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
        # Explicit caller configuration wins. Otherwise infer the linear unit
        # from DXF $INSUNITS; unitless/unsupported values conservatively fall
        # back to the application's historical millimetre assumption.
        units_override = "units" in kwargs
        units = kwargs.get("units", "mm")
        drawing_id = os.path.splitext(os.path.basename(file_path))[0]

        try:
            doc = ezdxf.readfile(file_path)
        except ezdxf.DXFError as e:
            logger.error("DXF読み込みエラー: %s - %s", file_path, e)
            drawing = Drawing(
                drawing_id=drawing_id,
                file_name=os.path.basename(file_path),
                file_type="dxf",
                scale=scale,
                units=units,
                elements=[],
            )
            drawing._meta = {"load_error": f"DXF読み込みエラー: {e}"}  # type: ignore[attr-defined]
            return drawing
        except Exception as e:
            logger.error("予期しないエラー: %s - %s", file_path, e)
            drawing = Drawing(
                drawing_id=drawing_id,
                file_name=os.path.basename(file_path),
                file_type="dxf",
                scale=scale,
                units=units,
                elements=[],
            )
            drawing._meta = {"load_error": f"予期しない読み込みエラー: {e}"}  # type: ignore[attr-defined]
            return drawing

        dxf_version = doc.dxfversion
        raw_insunits = doc.header.get("$INSUNITS", 0)
        try:
            dxf_insunits = int(raw_insunits or 0)
        except (TypeError, ValueError, OverflowError):
            # Malformed unit metadata must not prevent otherwise readable
            # geometry from loading; use the documented fallback instead.
            logger.warning("DXF $INSUNITS が不正なため既定単位を使用します: %r", raw_insunits)
            dxf_insunits = 0
        insunits_to_unit = {1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m"}
        inferred_units = insunits_to_unit.get(dxf_insunits)
        units_source = "explicit_argument" if units_override else (
            "dxf_insunits" if inferred_units else "default_mm"
        )
        if not units_override and inferred_units:
            units = inferred_units
        msp = doc.modelspace()

        logger.info("DXF読み込み完了: %s (version=%s)", file_path, dxf_version)

        elements: List[DrawingElement] = []
        unsupported_types: Dict[str, int] = {}
        element_counter = 0
        failed_types: Dict[str, int] = {}
        expanded_inserts = 0
        insert_markers = 0

        for entity in msp:
            etype = entity.dxftype()
            try:
                if etype == "INSERT":
                    expanded = self._expand_insert(doc, entity, element_counter)
                    if expanded:
                        elements.extend(expanded)
                        element_counter += len(expanded)
                        expanded_inserts += 1
                        continue
                    # 展開できない参照はマーカー要素として残す。
                    insert_markers += 1
                elem = self._convert_entity(entity, element_counter)
                if elem is not None:
                    elements.append(elem)
                    element_counter += 1
                else:
                    unsupported_types[etype] = unsupported_types.get(etype, 0) + 1
            except Exception as e:
                failed_types[etype] = failed_types.get(etype, 0) + 1
                logger.warning("エンティティ変換スキップ (%s): %s", etype, e)

        # ログ出力
        logger.info("取得要素数: %d", len(elements))
        if unsupported_types:
            logger.info("未対応エンティティ（スキップ）: %s", unsupported_types)
        if failed_types:
            logger.warning("変換失敗エンティティ: %s", failed_types)

        units_warning = _check_unit_plausibility(elements, units, units_source)
        if units_warning:
            logger.warning("%s", units_warning)

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
            "dxf_insunits": dxf_insunits,
            "units_source": units_source,
            "units_warning": units_warning,
            "expanded_inserts": expanded_inserts,
            "insert_markers": insert_markers,
            "unsupported_types": unsupported_types,
            "failed_types": failed_types,
            "layers": {layer.dxf.name: {"color": abs(layer.dxf.color), "is_on": layer.is_on()} for layer in doc.layers},
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
                "color": abs(layer.dxf.color),  # 負数は非表示フラグなので、色番号は正規化する
                "is_on": layer.is_on(),
            })
        return layers

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _convert_entity(self, entity, index: int) -> Optional[DrawingElement]:
        """DXFエンティティを DrawingElement サブクラスへ変換する。"""
        etype = entity.dxftype()
        eid = f"{etype}_{index:06d}"
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
        elif etype == "INSERT":
            return self._convert_insert(entity, eid, layer, color)
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
        # LWPOLYLINEはXY座標 + bulge を取得
        points = []
        bulge_list = []
        for pt in entity.get_points("xyb"):
            points.append([pt[0], pt[1]])
            bulge_list.append(float(pt[2]) if len(pt) > 2 else 0.0)
        is_closed = bool(entity.closed)
        return PolylineElement(
            element_id=eid,
            element_type="POLYLINE",
            layer=layer,
            color=color,
            points=points,
            is_closed=is_closed,
            bulge_list=bulge_list,
        )

    def _convert_polyline(self, entity, eid, layer, color) -> PolylineElement:
        points = []
        bulge_list = []
        # Never return a partially converted polyline. In particular, a
        # truncated closed boundary could produce a misleading room area.
        # The caller records conversion failures and continues with later
        # entities in the DXF.
        for vertex in entity.vertices:
            pt = vertex.dxf.location
            points.append([float(pt.x), float(pt.y)])
            bulge_list.append(float(vertex.dxf.get("bulge", 0.0)))
        is_closed = bool(entity.is_closed)
        return PolylineElement(
            element_id=eid,
            element_type="POLYLINE",
            layer=layer,
            color=color,
            points=points,
            is_closed=is_closed,
            bulge_list=bulge_list,
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
        style = entity.dxf.get("style", "")
        return TextElement(
            element_id=eid,
            element_type="TEXT",
            layer=layer,
            color=color,
            text=str(text),
            insertion_point=[float(insert[0]), float(insert[1])],
            height=height,
            rotation=rotation,
            style=str(style),
        )

    def _convert_mtext(self, entity, eid, layer, color) -> TextElement:
        text = ""
        if hasattr(entity, "plain_text"):
            try:
                text = entity.plain_text()
            except Exception:
                pass
        if not text and hasattr(entity, "plain_mtext"):
            try:
                text = entity.plain_mtext()
            except Exception:
                pass
        if not text and hasattr(entity, "text"):
            text = entity.text
        if not text and hasattr(entity, "dxf"):
            text = entity.dxf.get("text", "")

        insert = entity.dxf.get("insert", (0.0, 0.0))
        height = float(entity.dxf.get("char_height", 2.5))
        rotation = float(entity.dxf.get("rotation", 0.0))
        style = entity.dxf.get("style", "")
        return TextElement(
            element_id=eid,
            element_type="MTEXT",   # TEXT と区別するために MTEXT を設定
            layer=layer,
            color=color,
            text=str(text),
            insertion_point=[float(insert[0]), float(insert[1])],
            height=height,
            rotation=rotation,
            style=str(style),
        )

    def _convert_insert(self, entity, eid, layer, color) -> InsertElement:
        """INSERT エンティティ（ブロック参照）を InsertElement へ変換する。

        ブロックを展開できない場合のフォールバック用。展開できる参照は
        _expand_insert が図形要素に変換するため、ここは呼ばれない。
        """
        block_name = entity.dxf.get("name", "")
        insert_pt = entity.dxf.get("insert", (0.0, 0.0))
        rotation = float(entity.dxf.get("rotation", 0.0))
        scale_x = float(entity.dxf.get("xscale", 1.0))
        scale_y = float(entity.dxf.get("yscale", 1.0))
        scale_z = float(entity.dxf.get("zscale", 1.0))
        return InsertElement(
            element_id=eid,
            element_type="INSERT",
            layer=layer,
            color=color,
            block_name=str(block_name),
            insert_point=[float(insert_pt[0]), float(insert_pt[1])],
            rotation=rotation,
            scale_x=scale_x,
            scale_y=scale_y,
            scale_z=scale_z,
        )

    # -----------------------------------------------------------------------
    # INSERT（ブロック参照）の展開
    # -----------------------------------------------------------------------

    def _insert_transform(self, entity):
        """Return (block_name, transform, layer, color) for an INSERT entity.

        The transform is a 2D affine map (a, b, c, d, tx, ty) combining
        the insertion point, rotation and x/y scale factors.
        """
        block_name = str(entity.dxf.get("name", "") or "")
        insert_pt = entity.dxf.get("insert", (0.0, 0.0))
        rotation = float(entity.dxf.get("rotation", 0.0))
        scale_x = float(entity.dxf.get("xscale", 1.0))
        scale_y = float(entity.dxf.get("yscale", 1.0))
        theta = math.radians(rotation)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        transform = (
            cos_t * scale_x, -sin_t * scale_y,
            sin_t * scale_x, cos_t * scale_y,
            float(insert_pt[0]), float(insert_pt[1]),
        )
        layer = entity.dxf.get("layer", "0")
        color = entity.dxf.get("color", None)
        return block_name, transform, layer, color

    def _expand_insert(self, doc, entity, index: int) -> List[DrawingElement]:
        """Expand one INSERT into its block contents, transformed to drawing space.

        Returns the expanded elements, or an empty list when the block
        cannot be expanded (missing block, special layout block, or a
        degenerate transform). The caller keeps the InsertElement marker
        in that case.
        """
        insert_eid = f"INSERT_{index:06d}"
        try:
            block_name, transform, layer, color = self._insert_transform(entity)
        except (TypeError, ValueError, OverflowError):
            return []
        if not block_name or block_name.startswith(("*Model", "*Paper")):
            return []
        det = transform[0] * transform[3] - transform[1] * transform[2]
        if not math.isfinite(det) or det == 0.0:
            return []
        if not all(math.isfinite(v) for v in transform):
            return []
        try:
            block = doc.blocks.get(block_name)
        except Exception:
            return []
        counter = [0]
        try:
            return self._expand_block_entities(
                doc, block, transform, insert_eid, block_name, layer, color,
                depth=0, stack=[block_name], counter=counter,
            )
        except Exception as exc:
            logger.warning("ブロック展開スキップ (%s): %s", block_name, exc)
            return []

    def _expand_block_entities(
        self, doc, block, transform, insert_eid, block_name,
        insert_layer, insert_color, depth, stack, counter,
    ) -> List[DrawingElement]:
        """Convert block entities with a transform; nested INSERTs recurse."""
        if depth > _MAX_BLOCK_EXPANSION_DEPTH:
            logger.warning("ブロック展開の深さ上限に達しました: %s", block_name)
            return []
        elements: List[DrawingElement] = []
        for entity in block:
            etype = entity.dxftype()
            try:
                if etype == "INSERT":
                    try:
                        nested_name, nested_transform, nested_layer, nested_color = (
                            self._insert_transform(entity)
                        )
                    except (TypeError, ValueError, OverflowError):
                        continue
                    if not nested_name or nested_name in stack:
                        logger.warning(
                            "ブロック参照の循環を回避しました: %s", nested_name or "?"
                        )
                        continue
                    try:
                        nested_block = doc.blocks.get(nested_name)
                    except Exception:
                        continue
                    composed = _compose_transform(transform, nested_transform)
                    det = composed[0] * composed[3] - composed[1] * composed[2]
                    if (
                        not math.isfinite(det)
                        or det == 0.0
                        or not all(math.isfinite(v) for v in composed)
                    ):
                        continue
                    # Entities on layer "0" inside a nested block inherit
                    # the outer insert's layer (DXF rule, applied per level).
                    effective_layer = (
                        nested_layer if nested_layer != "0" else insert_layer
                    )
                    elements.extend(self._expand_block_entities(
                        doc, nested_block, composed, insert_eid, nested_name,
                        effective_layer,
                        nested_color if nested_color is not None else insert_color,
                        depth + 1, stack + [nested_name], counter,
                    ))
                    continue
                elem = self._convert_entity(entity, counter[0])
                if elem is None:
                    continue
                transformed = self._apply_transform(elem, transform)
                if transformed is None:
                    logger.warning(
                        "ブロック内要素をスキップ (非均一倍率で表現不可: %s)", etype
                    )
                    continue
            except Exception as exc:
                logger.warning("ブロック内要素の変換スキップ (%s): %s", etype, exc)
                continue
            counter[0] += 1
            transformed.element_id = f"{insert_eid}__{counter[0]:03d}"
            if transformed.layer == "0":
                transformed.layer = insert_layer
            if transformed.color == 0 and insert_color is not None:
                transformed.color = insert_color
            transformed.properties["block_name"] = block_name
            transformed.properties["source_insert_id"] = insert_eid
            elements.append(transformed)
        return elements

    def _apply_transform(self, elem, transform) -> Optional[DrawingElement]:
        """Apply a 2D affine transform to a converted element in place.

        Returns None for geometry that cannot be represented after the
        transform (circles/arcs under non-uniform scale, which become
        ellipses). Polyline bulge values are kept unchanged: exact under
        rotation and uniform scale, approximate under non-uniform scale.
        """
        if isinstance(elem, LineElement):
            elem.start = _transform_point(transform, elem.start)
            elem.end = _transform_point(transform, elem.end)
        elif isinstance(elem, PolylineElement):
            elem.points = [
                _transform_point(transform, pt) for pt in elem.points
            ]
        elif isinstance(elem, ArcElement):
            scale = _uniform_scale(transform)
            if scale is None:
                return None
            elem.center = _transform_point(transform, elem.center)
            elem.radius = float(elem.radius) * scale
            elem.start_angle = _transform_angle(transform, elem.start_angle)
            elem.end_angle = _transform_angle(transform, elem.end_angle)
        elif isinstance(elem, CircleElement):
            scale = _uniform_scale(transform)
            if scale is None:
                return None
            elem.center = _transform_point(transform, elem.center)
            elem.radius = float(elem.radius) * scale
        elif isinstance(elem, TextElement):
            det = transform[0] * transform[3] - transform[1] * transform[2]
            elem.insertion_point = _transform_point(
                transform, elem.insertion_point
            )
            elem.height = float(elem.height) * math.sqrt(abs(det))
            elem.rotation = _transform_angle(transform, elem.rotation)
        elif isinstance(elem, InsertElement):
            # Nested inserts are expanded by the caller, never transformed here.
            return None
        return elem
