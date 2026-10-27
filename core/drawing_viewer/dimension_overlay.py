"""
core.drawing_viewer.dimension_overlay
寸法照合の結果を図面上の ANALYSIS レイヤーへ描画するオーバーレイ。
寸法線の位置に色付きの印（一致＝緑、不一致＝赤、要確認＝黄、
判定不能＝灰色）を付け、寸法値と実測長を表示する。

注意：オーバーレイの各寸法は QGraphicsItemGroup としてシーンへ直接
追加する（Z 値 10）。QGraphicsItemGroup の子要素は選択できないため、
ANALYSIS レイヤーグループへ入れるとクリック選択ができなくなる。
その代わり、作成したアイテムはレンダラーが保持し、clear() で
シーンから直接取り除く。
"""
import logging
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsSimpleTextItem,
)
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPen, QBrush, QColor, QFont

from core.analyzer.dimension_check import STATUS_LABELS, DimensionCheck
from core.drawing_viewer.scene import DrawingScene, DrawingLayer
from core.models.drawing import Drawing, LineElement, PolylineElement

logger = logging.getLogger(__name__)

# シーンアイテムに寸法 ID を格納するデータ役割。
# Qt.UserRole は DXF 要素 ID、UserRole+1 は部屋 ID に使われている。
DIMENSION_ITEM_ROLE = Qt.ItemDataRole.UserRole + 2

# 照合状態ごとの表示スタイル（ダークテーマの画面上で区別しやすい色）。
_STATUS_STYLES = {
    "matched": {
        "pen": QColor("#9ece6a"),   # 緑：一致
        "brush": QColor(158, 206, 106, 60),
    },
    "mismatched": {
        "pen": QColor("#f7768e"),   # 赤：不一致
        "brush": QColor(247, 118, 142, 60),
    },
    "to_confirm": {
        "pen": QColor("#e0af68"),   # 琥珀色：要確認
        "brush": QColor(224, 175, 104, 60),
    },
    "not_determinable": {
        "pen": QColor("#565f89"),   # グレー：判定不能
        "brush": QColor(86, 95, 137, 40),
    },
}

# 印の画面上の半径（px）。変換を無視するためズームしても同じ大きさ。
_MARKER_RADIUS_PX = 8.0


def dimension_label_text(check: DimensionCheck) -> str:
    """オーバーレイに表示する寸法ラベル（寸法値 / 実測長）。"""
    value = f"{check.value_mm:.0f}"
    if check.measured_mm is None:
        return f"{value} / ―"
    return f"{value} / {check.measured_mm:.0f}"


def dimension_detail_text(check: DimensionCheck) -> str:
    """寸法の詳細（ツールチップ・一覧表示用）。"""
    status = STATUS_LABELS.get(check.status, check.status)
    lines = [
        f"寸法 {check.dimension_text}（{check.value_mm:.2f} mm）",
        f"状態：{status}",
    ]
    if check.measured_mm is not None:
        lines.append(f"実測長：{check.measured_mm:.2f} mm")
    if check.difference_mm is not None:
        lines.append(f"差分：{check.difference_mm:+.2f} mm")
    if check.tolerance_mm is not None:
        lines.append(f"許容誤差：±{check.tolerance_mm:.2f} mm")
    lines.append(f"確信度：{check.confidence:.2f}")
    if check.reason:
        lines.append(check.reason)
    return "\n".join(lines)


class DimensionOverlayRenderer:
    """寸法照合の結果を DrawingScene へ描画する（ANALYSIS 相当の Z 値 10）。

    描画したアイテムは内部で保持し、clear() でシーンから取り除く。
    """

    def __init__(self):
        self._items: Dict[str, QGraphicsItemGroup] = {}

    def render_checks(
        self,
        checks: List[DimensionCheck],
        drawing: Drawing,
        scene: DrawingScene,
    ) -> Dict[str, QGraphicsItemGroup]:
        """寸法照合の結果を描画し、寸法 ID → グループの対応を返す。

        寸法線の要素が見つからない照合結果は描画を省略する。
        既存のオーバーレイは消さずに追加する。描き直す場合は
        呼び出し側で先に clear() すること。
        """
        rendered: Dict[str, QGraphicsItemGroup] = {}
        for check in checks:
            group = self._create_dimension_group(check, drawing)
            if group is None:
                continue
            group.setZValue(float(DrawingLayer.ANALYSIS))
            scene.addItem(group)
            self._items[check.dimension_id] = group
            rendered[check.dimension_id] = group
        logger.info("寸法照合オーバーレイ描画: %d 件", len(rendered))
        return rendered

    def clear(self, scene: DrawingScene) -> None:
        """描画したオーバーレイをすべてシーンから取り除く。"""
        for group in list(self._items.values()):
            scene.removeItem(group)
        self._items.clear()

    def set_visible(self, visible: bool) -> None:
        """描画したオーバーレイの表示/非表示を切り替える。"""
        for group in self._items.values():
            group.setVisible(visible)

    # ------------------------------------------------------------------
    # プライベートメソッド
    # ------------------------------------------------------------------

    def _create_dimension_group(
        self, check: DimensionCheck, drawing: Drawing
    ) -> Optional[QGraphicsItemGroup]:
        position = self._dimension_line_midpoint(check, drawing)
        if position is None:
            logger.warning("寸法線が見つからないため描画を省略: %s", check.dimension_id)
            return None

        style = _STATUS_STYLES.get(check.status)
        if style is None:
            style = _STATUS_STYLES["not_determinable"]

        group = QGraphicsItemGroup()
        group.setData(DIMENSION_ITEM_ROLE, check.dimension_id)
        group.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        group.setToolTip(dimension_detail_text(check))

        # 色付きの印（円）。ズームしても同じ画面サイズで表示する。
        marker = QGraphicsEllipseItem(
            -_MARKER_RADIUS_PX, -_MARKER_RADIUS_PX,
            _MARKER_RADIUS_PX * 2, _MARKER_RADIUS_PX * 2,
        )
        pen = QPen(style["pen"])
        pen.setCosmetic(True)
        pen.setWidth(2)
        marker.setPen(pen)
        marker.setBrush(QBrush(style["brush"]))
        marker.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        marker.setPos(QPointF(position[0], -position[1]))
        group.addToGroup(marker)

        # 寸法値 / 実測長ラベル。印の位置から表示する。
        label = QGraphicsSimpleTextItem(dimension_label_text(check))
        font = QFont("Yu Gothic UI", 11)
        label.setFont(font)
        label.setBrush(style["pen"])
        label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        label.setPos(QPointF(position[0], -position[1]))
        group.addToGroup(label)

        return group

    @staticmethod
    def _dimension_line_midpoint(
        check: DimensionCheck, drawing: Drawing
    ) -> Optional[tuple]:
        """寸法線の中点（Drawing 座標）を返す。見つからなければ None。"""
        if not check.dimension_line_id:
            return None
        element = drawing.get_element_by_id(check.dimension_line_id)
        if element is None:
            return None
        if isinstance(element, LineElement):
            return (
                (float(element.start[0]) + float(element.end[0])) / 2.0,
                (float(element.start[1]) + float(element.end[1])) / 2.0,
            )
        if isinstance(element, PolylineElement) and element.points:
            xs = [float(p[0]) for p in element.points]
            ys = [float(p[1]) for p in element.points]
            return (sum(xs) / len(xs), sum(ys) / len(ys))
        return None
