"""
tests.test_analyzer
DrawingAnalyzer（構造解析エンジンの統計集計・文字列検索機能）の単体テスト。
"""

import pytest

from core.models.drawing import (
    Drawing, LineElement, CircleElement, TextElement, InsertElement
)
from core.analyzer.drawing_analyzer import DrawingAnalyzer, DrawingStats, LayerStats


def _create_sample_drawing() -> Drawing:
    drawing = Drawing(drawing_id="dummy_01", file_name="dummy.dxf", file_type="dxf")
    drawing.elements.extend([
        LineElement(element_id="LINE_001", element_type="LINE", layer="WALL", start=(0, 0), end=(100, 0)),
        LineElement(element_id="LINE_002", element_type="LINE", layer="WALL", start=(100, 0), end=(100, 100)),
        CircleElement(element_id="CIRC_001", element_type="CIRCLE", layer="COL", center=(50, 50), radius=10),
        TextElement(element_id="TEXT_001", element_type="TEXT", layer="ROOM", text="リビング", height=200, insertion_point=(50, 50)),
        TextElement(element_id="TEXT_002", element_type="TEXT", layer="ROOM", text="ダイニング", height=200, insertion_point=(150, 50)),
        InsertElement(element_id="INST_001", element_type="INSERT", layer="DOOR", block_name="W800", insert_point=(0, 50)),
    ])
    return drawing



def test_drawing_analyzer_stats():
    drawing = _create_sample_drawing()
    stats = DrawingAnalyzer.analyze(drawing)

    assert isinstance(stats, DrawingStats)
    assert stats.total_elements == 6
    assert stats.layer_count == 4
    assert set(stats.layers.keys()) == {"WALL", "COL", "ROOM", "DOOR"}

    # 種別毎の集計
    assert stats.by_type.get("LINE") == 2
    assert stats.by_type.get("CIRCLE") == 1
    assert stats.by_type.get("TEXT") == 2
    assert stats.by_type.get("INSERT") == 1

    # WALL レイヤーの集計
    wall_stats = stats.layers["WALL"]
    assert isinstance(wall_stats, LayerStats)
    assert wall_stats.name == "WALL"
    assert wall_stats.total == 2
    assert wall_stats.by_type.get("LINE") == 2


def test_drawing_analyzer_text_search():
    drawing = _create_sample_drawing()

    # 部分一致検索 "リビング"
    results = DrawingAnalyzer.search_text(drawing, "リビング")
    assert len(results) == 1
    assert results[0].text == "リビング"

    # あいまい・部分一致検索 "グ" (リビング, ダイニング の両方に一致)
    results_g = DrawingAnalyzer.search_text(drawing, "グ")
    assert len(results_g) == 2


    # 該当なし
    results_none = DrawingAnalyzer.search_text(drawing, "和室")
    assert len(results_none) == 0


def test_drawing_analyzer_filters():
    drawing = _create_sample_drawing()

    # レイヤー別フィルター
    room_elems = DrawingAnalyzer.get_elements_by_layer(drawing, "ROOM")
    assert len(room_elems) == 2

    # 種別別フィルター
    text_elems = DrawingAnalyzer.get_elements_by_type(drawing, "TEXT")
    assert len(text_elems) == 2

    # レイヤー名一覧
    layers = DrawingAnalyzer.get_layer_names(drawing)
    assert set(layers) == {"WALL", "COL", "ROOM", "DOOR"}
