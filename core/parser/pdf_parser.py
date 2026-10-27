"""ベクトル PDF を読み込み、共通の Drawing モデルへ変換するパーサー。

PyMuPDF を使い、ページ内のベクトル描画命令と文字を抽出する。
PDF の座標は pt（1/72 インチ）で左上原点・Y 下向きのため、
Drawing の座標系（Y 上向き・mm）に変換して格納する。

方針（曖昧なものは推測しない）:
- 換算率（mm/pt）は PDF 内に存在しないため、呼び出し側が
  ``scale_mm_per_pt`` で指定する。未指定の場合は 1pt=1mm として
  読み込み、``_meta`` に ``units_source: "not_determined"`` と警告を残す。
- ベジェ曲線（``c``）と四角形（``qu``）は DXF の bulge 同様に
  この版では非対応とし、要素化せず件数を ``_meta`` に記録する。
- 塗りつぶしのみの描画（``fill``）は線ではないため要素化せず、
  件数を ``_meta`` に記録する。
- 複数ページの PDF は 1 ページ目のみ読み込む。
- スキャン PDF（描画命令も文字もない）は要素 0 件とし、警告を残す。
  OCR はこの版の対象外。
"""
from __future__ import annotations

import logging
import os
from typing import Dict, Any, List, Optional

import pymupdf

from core.parser.interface import IDrawingParser
from core.models.drawing import (
    Drawing, DrawingElement, LineElement, PolylineElement, TextElement,
)

logger = logging.getLogger(__name__)

# 近接する span を 1 つの文字要素にまとめる判定に使う、フォントサイズ
# に対する許容ギャップ。単語内の文字間はフォントサイズの半分以下に
# 収まるのが普通で、単語間の空白はそれより広い。
_MERGE_GAP_FACTOR = 0.5
# ギャップがこの倍率以下の場合は空白を入れずに連結する。
_JOIN_WITHOUT_SPACE_FACTOR = 0.15

# 文字化けの判定に使う文字。PyMuPDF はグリフに対応する Unicode が
# ない文字を U+FFFD で返し、埋め込みフォントのない日本語などは
# 中点（·）の並びになることがある。
_REPLACEMENT_CHAR = "\ufffd"
_MISSING_GLYPH_CHAR = "·"


def _is_garbled_text(text: str) -> bool:
    """文字化けしたテキストかどうかを判定する。

    置換文字を含む場合、または空白以外の文字がすべて中点の場合に
    文字化けとみなす。普通の日本語・英数字のテキストは該当しない。
    """
    if not text:
        return False
    if _REPLACEMENT_CHAR in text:
        return True
    non_space = [ch for ch in text if not ch.isspace()]
    if non_space and all(ch == _MISSING_GLYPH_CHAR for ch in non_space):
        return True
    return False


def _merge_spans(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同じ行の近接する span を 1 つの span にまとめる。

    PDF の生成元によっては 1 つの文字列が複数の span に分かれる
    （例: "40" と "00"）ため、横方向のギャップがフォントサイズの
    半分以下の span 同士を連結する。ギャップが広い場合は単語の区切り
    として空白を入れる。
    """
    if not spans:
        return []
    ordered = sorted(spans, key=lambda s: s["bbox"][0])
    merged: List[Dict[str, Any]] = []
    current = dict(ordered[0])
    current["text"] = str(current.get("text", ""))
    for nxt in ordered[1:]:
        gap = float(nxt["bbox"][0]) - float(current["bbox"][2])
        size = max(float(current.get("size", 0.0)), float(nxt.get("size", 0.0)), 0.1)
        if gap <= _MERGE_GAP_FACTOR * size:
            joiner = "" if gap <= _JOIN_WITHOUT_SPACE_FACTOR * size else " "
            current["text"] = current["text"] + joiner + str(nxt.get("text", ""))
            current["bbox"] = (
                min(current["bbox"][0], nxt["bbox"][0]),
                min(current["bbox"][1], nxt["bbox"][1]),
                max(current["bbox"][2], nxt["bbox"][2]),
                max(current["bbox"][3], nxt["bbox"][3]),
            )
            current["size"] = max(current.get("size", 0.0), nxt.get("size", 0.0))
        else:
            merged.append(current)
            current = dict(nxt)
            current["text"] = str(current.get("text", ""))
    merged.append(current)
    return merged


class PdfParser(IDrawingParser):
    """ベクトル PDF 用のパーサー（PyMuPDF を使用）。"""

    def parse(self, file_path: str, **kwargs) -> Drawing:
        """PDF ファイルを読み込んで Drawing オブジェクトを返す。

        Args:
            file_path: 解析対象の PDF ファイルのパス。
            **kwargs: ``scale_mm_per_pt``（1pt あたりの mm。未指定の場合は
                1.0 として読み込み、``_meta`` に未確定の旨を記録する）。
                ``mm_per_pt`` も同じ意味の別名として受け付ける。

        Returns:
            Drawing オブジェクト。読み込み失敗時は空の Drawing を返し、
            ``_meta["load_error"]`` に理由を記録する。
        """
        drawing_id = os.path.splitext(os.path.basename(file_path))[0]
        mm_per_pt = kwargs.get("scale_mm_per_pt", kwargs.get("mm_per_pt"))
        units_source = "explicit" if mm_per_pt is not None else "not_determined"
        if mm_per_pt is None:
            mm_per_pt = 1.0
        try:
            mm_per_pt = float(mm_per_pt)
        except (TypeError, ValueError):
            mm_per_pt = 1.0
            units_source = "not_determined"
        if mm_per_pt <= 0:
            mm_per_pt = 1.0
            units_source = "not_determined"

        try:
            doc = pymupdf.open(file_path)
        except Exception as exc:  # ファイルが存在しない・PDF ではない等
            logger.error("PDF読み込みエラー: %s - %s", file_path, exc)
            drawing = Drawing(
                drawing_id=drawing_id,
                file_name=os.path.basename(file_path),
                file_type="pdf",
                scale=mm_per_pt,
                units="mm",
                elements=[],
            )
            drawing._meta = {"load_error": f"PDF読み込みエラー: {exc}"}  # type: ignore[attr-defined]
            return drawing

        try:
            page_count = len(doc)
            page = doc[0]
            page_width = float(page.rect.width)
            page_height = float(page.rect.height)

            elements: List[DrawingElement] = []
            element_counter = 0
            unsupported_curve_items = 0
            skipped_fill_drawings = 0
            skipped_degenerate = 0
            garbled_spans_skipped = 0
            text_garbled = False

            def to_mm_x(x_pt: float) -> float:
                return float(x_pt) * mm_per_pt

            def to_mm_y(y_pt: float) -> float:
                # PDF は左上原点・Y 下向き。Drawing は Y 上向き。
                return (page_height - float(y_pt)) * mm_per_pt

            def layer_of(item: Dict[str, Any]) -> str:
                name = item.get("layer") or ""
                return str(name) if str(name).strip() else "0"

            def style_props(item: Dict[str, Any]) -> Dict[str, Any]:
                color = item.get("color")
                fill = item.get("fill")
                return {
                    "pdf_color": list(color) if color is not None else None,
                    "pdf_fill": list(fill) if fill is not None else None,
                    "pdf_width": item.get("width"),
                    "pdf_dashes": item.get("dashes"),
                    "pdf_type": item.get("type"),
                }

            for item in page.get_drawings():
                draw_type = str(item.get("type") or "")
                if "s" not in draw_type:
                    # 塗りつぶしのみの描画は線ではないため要素化しない。
                    skipped_fill_drawings += 1
                    continue
                layer = layer_of(item)
                props = style_props(item)
                for op, *args in item.get("items", []):
                    if op == "l":
                        p1, p2 = args[0], args[1]
                        start = [to_mm_x(p1.x), to_mm_y(p1.y)]
                        end = [to_mm_x(p2.x), to_mm_y(p2.y)]
                        if start == end:
                            skipped_degenerate += 1
                            continue
                        element_counter += 1
                        elements.append(LineElement(
                            element_id=f"PDF{element_counter:06d}",
                            element_type="LINE",
                            layer=layer,
                            start=start,
                            end=end,
                            properties=dict(props),
                        ))
                    elif op == "re":
                        rect = args[0]
                        corners = [
                            [to_mm_x(rect.x0), to_mm_y(rect.y0)],
                            [to_mm_x(rect.x1), to_mm_y(rect.y0)],
                            [to_mm_x(rect.x1), to_mm_y(rect.y1)],
                            [to_mm_x(rect.x0), to_mm_y(rect.y1)],
                        ]
                        if len({tuple(c) for c in corners}) < 4:
                            skipped_degenerate += 1
                            continue
                        element_counter += 1
                        elements.append(PolylineElement(
                            element_id=f"PDF{element_counter:06d}",
                            element_type="POLYLINE",
                            layer=layer,
                            points=corners,
                            is_closed=True,
                            properties=dict(props),
                        ))
                    elif op in ("c", "qu"):
                        # ベジェ曲線・四角形はこの版では非対応（直線近似しない）。
                        unsupported_curve_items += 1
                    # その他の描画命令は上記の種別で処理済み。

            # 文字の抽出。行ごとに span をまとめ、文字化けした span は
            # 部屋名・寸法として誤用されないよう除外する。
            text_dict = page.get_text("dict")
            for block in text_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    spans = [s for s in line.get("spans", []) if str(s.get("text", "")).strip()]
                    for span in _merge_spans(spans):
                        text = str(span.get("text", ""))
                        if _is_garbled_text(text):
                            text_garbled = True
                            garbled_spans_skipped += 1
                            continue
                        origin = span.get("origin", (0.0, 0.0))
                        bbox = span.get("bbox", (0.0, 0.0, 0.0, 0.0))
                        size_pt = float(span.get("size", 0.0))
                        element_counter += 1
                        elements.append(TextElement(
                            element_id=f"PDF{element_counter:06d}",
                            element_type="TEXT",
                            layer="0",
                            text=text,
                            insertion_point=[to_mm_x(origin[0]), to_mm_y(origin[1])],
                            height=size_pt * mm_per_pt,
                            rotation=0.0,
                            bbox=[
                                to_mm_x(bbox[0]),
                                to_mm_y(bbox[3]),
                                to_mm_x(bbox[2]),
                                to_mm_y(bbox[1]),
                            ],
                            properties={"pdf_font": span.get("font", "")},
                        ))

            units_warning: Optional[str] = None
            if units_source == "not_determined":
                units_warning = (
                    "PDF には実寸への換算率が含まれていないため、"
                    "1pt=1mm として読み込みました。寸法と照合して"
                    "倍率調整を行ってください。"
                )
                logger.warning("%s", units_warning)

            scanned_warning: Optional[str] = None
            if not elements:
                scanned_warning = (
                    "ベクトル要素が抽出できませんでした。"
                    "スキャン PDF（画像のみ）の可能性があります。"
                    "OCR はこの版の対象外です。"
                )
                logger.warning("%s", scanned_warning)

            text_warning: Optional[str] = None
            if text_garbled:
                text_warning = (
                    "一部の文字が文字化けしているため読み取れませんでした"
                    "（フォントが埋め込まれていない可能性があります）。"
                )
                logger.warning("%s", text_warning)

            drawing = Drawing(
                drawing_id=drawing_id,
                file_name=os.path.basename(file_path),
                file_type="pdf",
                scale=mm_per_pt,
                units="mm",
                elements=elements,
            )
            drawing._meta = {  # type: ignore[attr-defined]
                "pdf_page_count": page_count,
                "pdf_page_used": 1,
                "pdf_page_note": (
                    "複数ページの PDF です。1 ページ目のみ読み込みました。"
                    if page_count > 1 else None
                ),
                "mm_per_pt": mm_per_pt,
                "units_source": units_source,
                "units_warning": units_warning,
                "unsupported_curve_items": unsupported_curve_items,
                "skipped_fill_drawings": skipped_fill_drawings,
                "skipped_degenerate": skipped_degenerate,
                "text_garbled": text_garbled,
                "text_garbled_warning": text_warning,
                "garbled_spans_skipped": garbled_spans_skipped,
                "scanned_pdf_warning": scanned_warning,
                "pdf_page_size_pt": [page_width, page_height],
            }
            logger.info("PDF読み込み完了: %s（要素数 %d）", file_path, len(elements))
            return drawing
        finally:
            doc.close()
