"""
core.analyzer.drawing_analyzer
Drawing オブジェクトから統計情報・構造化情報を抽出するアナライザー。
AIを使用せず、決定論的な計算のみで処理する。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Any

from core.models.drawing import Drawing, DrawingElement


# ---------------------------------------------------------------------------
# 統計データクラス
# ---------------------------------------------------------------------------

@dataclass
class LayerStats:
    """レイヤーごとの統計情報"""
    name: str
    total: int = 0
    by_type: Dict[str, int] = field(default_factory=dict)

    def add(self, element_type: str) -> None:
        self.total += 1
        self.by_type[element_type] = self.by_type.get(element_type, 0) + 1


@dataclass
class DrawingStats:
    """図面全体の統計情報"""
    total_elements: int = 0
    by_type: Dict[str, int] = field(default_factory=dict)
    layer_count: int = 0
    layers: Dict[str, LayerStats] = field(default_factory=dict)

    def summary_text(self) -> str:
        """統計情報を人間が読みやすいテキストで返す。"""
        lines = [
            f"総要素数：{self.total_elements:,}",
            "",
        ]
        # エンティティ種別
        for etype, count in sorted(self.by_type.items(), key=lambda x: -x[1]):
            lines.append(f"  {etype:<16} {count:>6,}")
        lines.append("")
        lines.append(f"レイヤー数：{self.layer_count}")
        return "\n".join(lines)

    def layer_summary(self) -> List[Dict[str, Any]]:
        """
        レイヤー別要素数の一覧を返す。

        Returns:
            [{"name": str, "total": int, "by_type": dict}, ...]
            総要素数の降順でソートされる。
        """
        result = []
        for ls in sorted(self.layers.values(), key=lambda x: -x.total):
            result.append({
                "name": ls.name,
                "total": ls.total,
                "by_type": dict(ls.by_type),
            })
        return result


# ---------------------------------------------------------------------------
# アナライザー本体
# ---------------------------------------------------------------------------

class DrawingAnalyzer:
    """
    Drawing オブジェクトから統計・構造化情報を抽出するアナライザー。

    Phase 2 機能:
        - エンティティ種別カウント
        - レイヤー別要素数カウント
        - レイヤー一覧取得
        - テキスト検索

    将来拡張 (Phase 3+):
        - 線分の接続グラフ生成
        - 閉領域探索のための前処理
    """

    @classmethod
    def analyze(cls, drawing: Drawing) -> DrawingStats:
        """
        Drawing を解析して DrawingStats を返す。

        Args:
            drawing: 解析対象の Drawing オブジェクト
        Returns:
            DrawingStats
        """
        stats = DrawingStats()
        layer_map: Dict[str, LayerStats] = {}

        for elem in drawing.elements:
            etype = elem.element_type
            layer_name = elem.layer or "0"

            # 総計
            stats.total_elements += 1
            stats.by_type[etype] = stats.by_type.get(etype, 0) + 1

            # レイヤー別
            if layer_name not in layer_map:
                layer_map[layer_name] = LayerStats(name=layer_name)
            layer_map[layer_name].add(etype)

        stats.layers = layer_map
        stats.layer_count = len(layer_map)
        return stats

    @classmethod
    def search_text(cls, drawing: Drawing, query: str,
                    case_sensitive: bool = False) -> List[DrawingElement]:
        """
        図面内の TEXT / MTEXT 要素からテキストを検索する。

        Args:
            drawing: 検索対象の Drawing
            query: 検索文字列
            case_sensitive: 大文字小文字を区別するか
        Returns:
            マッチした DrawingElement のリスト
        """
        from core.models.drawing import TextElement
        results = []
        q = query if case_sensitive else query.lower()
        for elem in drawing.elements:
            if not isinstance(elem, TextElement):
                continue
            text = elem.text if case_sensitive else elem.text.lower()
            if q in text:
                results.append(elem)
        return results

    @classmethod
    def get_elements_by_layer(cls, drawing: Drawing,
                                layer_name: str) -> List[DrawingElement]:
        """指定レイヤーの要素一覧を返す。"""
        return [e for e in drawing.elements if e.layer == layer_name]

    @classmethod
    def get_elements_by_type(cls, drawing: Drawing,
                              element_type: str) -> List[DrawingElement]:
        """指定エンティティ種別の要素一覧を返す。"""
        return [e for e in drawing.elements if e.element_type == element_type]

    @classmethod
    def get_layer_names(cls, drawing: Drawing) -> List[str]:
        """図面内のレイヤー名一覧を返す（要素数降順）。"""
        counter: Dict[str, int] = defaultdict(int)
        for elem in drawing.elements:
            counter[elem.layer or "0"] += 1
        return sorted(counter.keys(), key=lambda k: -counter[k])

