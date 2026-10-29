"""
core.drawing_viewer.room_overlay
検出した部屋候補を図面上の ANALYSIS レイヤーへ描画するオーバーレイ。
境界ポリゴンと部屋名・面積ラベルを表示し、確認状態ごとに色を変える。

注意：オーバーレイの各部屋は QGraphicsItemGroup としてシーンへ直接
追加する（Z 値 10）。QGraphicsItemGroup の子要素は選択できないため、
ANALYSIS レイヤーグループへ入れるとクリック選択ができなくなる。
その代わり、作成したアイテムはレンダラーが保持し、clear() で
シーンから直接取り除く。
"""
import logging
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsPathItem,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)
from PySide6.QtCore import Qt, QPointF, QRectF, QSizeF
from PySide6.QtGui import QPen, QBrush, QColor, QPainterPath, QFont
from shapely.geometry import Polygon

from core.drawing_viewer.scene import DrawingScene, DrawingLayer
from core.models.room import (
    REVIEW_STATUS_CONFIRMED,
    REVIEW_STATUS_LABELS,
    REVIEW_STATUS_REJECTED,
    REVIEW_STATUS_TO_CONFIRM,
    Room,
)

logger = logging.getLogger(__name__)

# シーンアイテムに部屋 ID を格納するデータ役割。
# Qt.UserRole は DXF 要素 ID に使われているため、部屋は +1 を使う。
ROOM_ITEM_ROLE = Qt.ItemDataRole.UserRole + 1

# 確認状態ごとの表示スタイル（ダークテーマの画面上で区別しやすい色）。
_STATUS_STYLES = {
    REVIEW_STATUS_TO_CONFIRM: {
        "pen": QColor("#e0af68"),   # 琥珀色：要確認
        "brush": QColor(224, 175, 104, 40),
        "dash": Qt.PenStyle.SolidLine,
    },
    REVIEW_STATUS_CONFIRMED: {
        "pen": QColor("#9ece6a"),   # 緑：確定
        "brush": QColor(158, 206, 106, 40),
        "dash": Qt.PenStyle.SolidLine,
    },
    REVIEW_STATUS_REJECTED: {
        "pen": QColor("#565f89"),   # グレー破線：却下
        "brush": QColor(86, 95, 137, 25),
        "dash": Qt.PenStyle.DashLine,
    },
}


def display_area(room: Room, area_basis: str) -> tuple[float, str]:
    """表示・出力に使う面積とその基準を返す。

    壁芯が選ばれ、かつその部屋に壁芯面積がある場合だけ壁芯面積を
    使い、それ以外は内法面積（room.area_m2）を使う。
    """
    if area_basis == "centerline":
        centerline = room.properties.get("area_centerline_m2")
        try:
            value = float(centerline)
        except (TypeError, ValueError, OverflowError):
            value = None
        if value is not None:
            return value, "centerline"
    return float(room.area_m2), "inner"


def room_label_text(room: Room, area_basis: str = "inner") -> str:
    """オーバーレイに表示する部屋ラベル（名前 + 面積）。"""
    name = room.room_name or "（未判定）"
    area, _basis = display_area(room, area_basis)
    return f"{name}\n{area:.2f} m²"


class RoomOverlayRenderer:
    """部屋候補を DrawingScene へ描画する（ANALYSIS 相当の Z 値 10）。

    描画したアイテムは内部で保持し、clear() でシーンから取り除く。
    """

    def __init__(self):
        self._items: Dict[str, QGraphicsItemGroup] = {}
        # 部屋 ID → (ラベル項目, 面積 m²)。ラベルの重なり整理で使う。
        self._labels: Dict[str, tuple] = {}

    def render_rooms(
        self,
        rooms: List[Room],
        scene: DrawingScene,
        area_basis: str = "inner",
    ) -> Dict[str, QGraphicsItemGroup]:
        """部屋一覧を描画し、部屋 ID → グループの対応を返す。

        area_basis が "centerline" の場合、壁芯面積がある部屋は
        壁芯面積でラベルを表示する（ない部屋は内法のまま）。
        既存のオーバーレイは消さずに追加する。描き直す場合は
        呼び出し側で先に clear() すること。
        """
        rendered: Dict[str, QGraphicsItemGroup] = {}
        for room in rooms:
            group = self._create_room_group(room, area_basis)
            if group is None:
                continue
            group.setZValue(float(DrawingLayer.ANALYSIS))
            scene.addItem(group)
            self._items[room.room_id] = group
            rendered[room.room_id] = group
        logger.info("部屋オーバーレイ描画: %d 件", len(rendered))
        return rendered

    def clear(self, scene: DrawingScene) -> None:
        """描画したオーバーレイをすべてシーンから取り除く。"""
        for group in list(self._items.values()):
            scene.removeItem(group)
        self._items.clear()
        self._labels.clear()

    def update_label_visibility(self, view: QGraphicsView) -> None:
        """画面上で重なる部屋ラベルの表示を整理する。

        ラベルは変換を無視して常に一定の画面サイズで描かれるため、
        全体表示では多数のラベルが重なって読めなくなる。面積の大きい
        部屋のラベルから順に、画面上で重ならないものだけを表示し、
        重なるものは隠す。ズームインすれば隠れたラベルも表示される。
        ビューが未設定・ラベルがない場合は何もしない。
        """
        if view is None or not self._labels:
            return
        # 面積の大きい部屋のラベルを優先する。
        ordered = sorted(
            self._labels.items(), key=lambda kv: -float(kv[1][1])
        )
        kept_rects: list = []
        margin = 2.0
        for _room_id, (label, _area) in ordered:
            try:
                anchor = view.mapFromScene(label.scenePos())
                size = label.boundingRect().size()
                rect = QRectF(
                    QPointF(float(anchor.x()), float(anchor.y())),
                    QSizeF(float(size.width()), float(size.height())),
                ).adjusted(-margin, -margin, margin, margin)
            except Exception:
                label.setVisible(True)
                continue
            if any(rect.intersects(kept) for kept in kept_rects):
                label.setVisible(False)
            else:
                label.setVisible(True)
                kept_rects.append(rect)

    def set_visible(self, visible: bool) -> None:
        """描画したオーバーレイの表示/非表示を切り替える。"""
        for group in self._items.values():
            group.setVisible(visible)

    # ------------------------------------------------------------------
    # プライベートメソッド
    # ------------------------------------------------------------------

    def _create_room_group(self, room: Room, area_basis: str = "inner") -> Optional[QGraphicsItemGroup]:
        boundary = room.boundary or []
        if len(boundary) < 3:
            logger.warning("部屋境界が不十分なため描画を省略: %s", room.room_id)
            return None

        style = _STATUS_STYLES.get(room.review_status)
        if style is None:
            style = _STATUS_STYLES[REVIEW_STATUS_TO_CONFIRM]

        group = QGraphicsItemGroup()
        group.setData(ROOM_ITEM_ROLE, room.room_id)
        group.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

        # 境界ポリゴン（DXF は Y 上向き、画面は Y 下向きのため反転する）。
        path = QPainterPath()
        first = boundary[0]
        path.moveTo(QPointF(float(first[0]), -float(first[1])))
        for point in boundary[1:]:
            path.lineTo(QPointF(float(point[0]), -float(point[1])))
        path.closeSubpath()

        polygon = QGraphicsPathItem(path)
        pen = QPen(style["pen"])
        pen.setCosmetic(True)  # ズームに関わらず常に一定の画面幅で描画
        pen.setStyle(style["dash"])
        polygon.setPen(pen)
        polygon.setBrush(QBrush(style["brush"]))
        group.addToGroup(polygon)

        # 部屋名・面積ラベル。重心に配置し、ズームしても文字が
        # 一定の大きさで読めるよう変換を無視する。
        label = QGraphicsSimpleTextItem(room_label_text(room, area_basis))
        font = QFont("Yu Gothic UI", 11)
        label.setFont(font)
        label.setBrush(style["pen"])
        label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        label.setPos(self._label_position(room))
        group.addToGroup(label)
        self._labels[room.room_id] = (label, float(room.area_m2))

        return group

    @staticmethod
    def _label_position(room: Room) -> QPointF:
        """ラベルの配置位置（境界の重心、Y 反転済み）。"""
        points = [(float(p[0]), float(p[1])) for p in room.boundary]
        try:
            centroid = Polygon(points).centroid
            return QPointF(centroid.x, -centroid.y)
        except Exception:
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            return QPointF(sum(xs) / len(xs), -sum(ys) / len(ys))
