"""PdfParser のテスト。PyMuPDF で合成ベクトル PDF を作って検証する。"""
import os

import pymupdf
import pytest

from core.models.drawing import LineElement, PolylineElement, TextElement
from core.parser.pdf_parser import PdfParser, _is_garbled_text, _merge_spans


def _make_two_room_pdf(path: str) -> None:
    """部屋 2 つ＋寸法線・引出線・寸法テキストを持つ合成 PDF を作る。

    ページ 1200x900pt。部屋1は 4000x3000mm 相当で寸法通り、
    部屋2は寸法 2000 に対して幅 2040mm 相当（2% ずれ）で描く。
    換算率は 10mm/pt を想定している。
    """
    doc = pymupdf.open()
    page = doc.new_page(width=1200, height=900)
    # 部屋1 (100,100)-(500,400)pt
    page.draw_rect(pymupdf.Rect(100, 100, 500, 400), color=(0, 0, 0), fill=None, width=1)
    page.draw_line(pymupdf.Point(100, 450), pymupdf.Point(500, 450), color=(0, 0, 0), width=0.5)
    page.draw_line(pymupdf.Point(100, 400), pymupdf.Point(100, 460), color=(0, 0, 0), width=0.5)
    page.draw_line(pymupdf.Point(500, 400), pymupdf.Point(500, 460), color=(0, 0, 0), width=0.5)
    page.insert_text((280, 440), "40", fontsize=12)
    page.insert_text((293.5, 440), "00", fontsize=12)
    # 部屋2 (600,100)-(804,400)pt（幅 204pt = 2040mm）
    page.draw_rect(pymupdf.Rect(600, 100, 804, 400), color=(0, 0, 0), fill=None, width=1)
    page.draw_line(pymupdf.Point(600, 450), pymupdf.Point(804, 450), color=(0, 0, 0), width=0.5)
    page.draw_line(pymupdf.Point(600, 400), pymupdf.Point(600, 460), color=(0, 0, 0), width=0.5)
    page.draw_line(pymupdf.Point(804, 400), pymupdf.Point(804, 460), color=(0, 0, 0), width=0.5)
    page.insert_text((660, 440), "2000", fontsize=12)
    # 日本語テキスト（基本フォントでは文字化けする）
    page.insert_text((100, 50), "会議室", fontsize=12)
    doc.save(path)
    doc.close()


def test_lines_and_rects_are_read_with_y_flip_and_mm_conversion(tmp_path):
    pdf_path = os.path.join(tmp_path, "two_rooms.pdf")
    _make_two_room_pdf(pdf_path)

    drawing = PdfParser().parse(pdf_path, scale_mm_per_pt=10.0)

    assert drawing.file_type == "pdf"
    assert drawing.units == "mm"
    assert drawing.scale == 10.0
    polylines = [e for e in drawing.elements if isinstance(e, PolylineElement)]
    lines = [e for e in drawing.elements if isinstance(e, LineElement)]
    assert len(polylines) == 2
    assert len(lines) == 6
    # 部屋1の矩形：PDF (100,100)-(500,400)pt が Y 反転して mm になる。
    # ページ高さ 900pt のため、y=100pt は (900-100)*10=8000mm になる。
    room1 = polylines[0]
    assert room1.is_closed
    assert room1.points[0] == [1000.0, 8000.0]
    assert room1.points[1] == [5000.0, 8000.0]
    assert room1.points[2] == [5000.0, 5000.0]
    assert room1.points[3] == [1000.0, 5000.0]
    # 線幅・色・破線が properties に退避されている。
    assert lines[0].properties["pdf_width"] == 0.5
    assert lines[0].properties["pdf_color"] == [0.0, 0.0, 0.0]


def test_text_spans_are_merged(tmp_path):
    pdf_path = os.path.join(tmp_path, "two_rooms.pdf")
    _make_two_room_pdf(pdf_path)

    drawing = PdfParser().parse(pdf_path, scale_mm_per_pt=10.0)

    texts = [e for e in drawing.elements if isinstance(e, TextElement)]
    assert [t.text for t in texts] == ["4000", "2000"]
    # "4000" は 2 つの span（"40" と "00"）が連結されたもの。
    dim_text = texts[0]
    assert dim_text.height == pytest.approx(120.0)
    assert dim_text.bbox is not None
    assert dim_text.bbox[0] == pytest.approx(2800.0)


def test_garbled_japanese_text_is_skipped(tmp_path):
    pdf_path = os.path.join(tmp_path, "two_rooms.pdf")
    _make_two_room_pdf(pdf_path)

    drawing = PdfParser().parse(pdf_path, scale_mm_per_pt=10.0)

    texts = [e.text for e in drawing.elements if isinstance(e, TextElement)]
    assert "会議室" not in texts
    assert not any("·" in t for t in texts)
    assert drawing._meta["text_garbled"] is True
    assert drawing._meta["garbled_spans_skipped"] == 1
    assert drawing._meta["text_garbled_warning"] is not None


def test_scale_not_determined_without_mm_per_pt(tmp_path):
    pdf_path = os.path.join(tmp_path, "two_rooms.pdf")
    _make_two_room_pdf(pdf_path)

    drawing = PdfParser().parse(pdf_path)

    assert drawing._meta["units_source"] == "not_determined"
    assert drawing._meta["units_warning"] is not None
    assert drawing.scale == 1.0
    # 換算率なしでは 1pt=1mm として読み込む。
    polylines = [e for e in drawing.elements if isinstance(e, PolylineElement)]
    assert polylines[0].points[0] == [100.0, 800.0]


def test_mm_per_pt_alias_kwarg(tmp_path):
    pdf_path = os.path.join(tmp_path, "two_rooms.pdf")
    _make_two_room_pdf(pdf_path)

    drawing = PdfParser().parse(pdf_path, mm_per_pt=10.0)

    assert drawing._meta["units_source"] == "explicit"
    assert drawing.scale == 10.0


def test_scanned_pdf_has_no_elements_and_warns(tmp_path):
    pdf_path = os.path.join(tmp_path, "blank.pdf")
    doc = pymupdf.open()
    doc.new_page(width=1200, height=900)
    doc.save(pdf_path)
    doc.close()

    drawing = PdfParser().parse(pdf_path, scale_mm_per_pt=10.0)

    assert drawing.elements == []
    assert drawing._meta["scanned_pdf_warning"] is not None


def test_curves_only_are_recorded_as_unsupported(tmp_path):
    pdf_path = os.path.join(tmp_path, "curve.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=1200, height=900)
    page.draw_bezier(
        pymupdf.Point(100, 100), pymupdf.Point(200, 50),
        pymupdf.Point(300, 150), pymupdf.Point(400, 100),
        color=(0, 0, 0), width=1,
    )
    doc.save(pdf_path)
    doc.close()

    drawing = PdfParser().parse(pdf_path, scale_mm_per_pt=10.0)

    assert drawing.elements == []
    assert drawing._meta["unsupported_curve_items"] == 1
    assert drawing._meta["scanned_pdf_warning"] is not None


def test_fill_only_drawings_are_skipped(tmp_path):
    pdf_path = os.path.join(tmp_path, "fill.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=1200, height=900)
    page.draw_rect(pymupdf.Rect(100, 100, 500, 400), color=None, fill=(0.9, 0.9, 0.9))
    doc.save(pdf_path)
    doc.close()

    drawing = PdfParser().parse(pdf_path, scale_mm_per_pt=10.0)

    assert drawing.elements == []
    assert drawing._meta["skipped_fill_drawings"] == 1


def test_multipage_pdf_reads_only_first_page(tmp_path):
    pdf_path = os.path.join(tmp_path, "multi.pdf")
    doc = pymupdf.open()
    page1 = doc.new_page(width=1200, height=900)
    page1.draw_rect(pymupdf.Rect(100, 100, 500, 400), color=(0, 0, 0), fill=None, width=1)
    page2 = doc.new_page(width=1200, height=900)
    page2.draw_rect(pymupdf.Rect(100, 100, 300, 300), color=(0, 0, 0), fill=None, width=1)
    doc.save(pdf_path)
    doc.close()

    drawing = PdfParser().parse(pdf_path, scale_mm_per_pt=10.0)

    assert drawing._meta["pdf_page_count"] == 2
    assert drawing._meta["pdf_page_used"] == 1
    assert drawing._meta["pdf_page_note"] is not None
    polylines = [e for e in drawing.elements if isinstance(e, PolylineElement)]
    assert len(polylines) == 1


def test_missing_file_returns_empty_drawing_with_error():
    drawing = PdfParser().parse("/tmp/does-not-exist-ada.pdf", scale_mm_per_pt=10.0)

    assert drawing.elements == []
    assert "load_error" in drawing._meta


def test_merge_spans_joins_adjacent_and_separates_distant():
    spans = [
        {"text": "40", "bbox": (280.0, 417.0, 293.3, 433.0), "size": 12.0},
        {"text": "00", "bbox": (293.5, 417.0, 306.8, 433.0), "size": 12.0},
        {"text": "会議室", "bbox": (400.0, 417.0, 440.0, 433.0), "size": 12.0},
    ]
    merged = _merge_spans(spans)
    assert [s["text"] for s in merged] == ["4000", "会議室"]


def test_merge_spans_joins_words_with_space():
    spans = [
        {"text": "Room", "bbox": (100.0, 417.0, 130.0, 433.0), "size": 12.0},
        {"text": "A", "bbox": (134.0, 417.0, 142.0, 433.0), "size": 12.0},
    ]
    merged = _merge_spans(spans)
    assert [s["text"] for s in merged] == ["Room A"]


def test_is_garbled_text():
    assert _is_garbled_text("···") is True
    assert _is_garbled_text("abc\ufffddef") is True
    assert _is_garbled_text("会議室") is False
    assert _is_garbled_text("4000") is False
    assert _is_garbled_text("A・B") is False
    assert _is_garbled_text("") is False
