"""寸法の抽出・照合と倍率調整のテスト。"""
import os

import pymupdf
import pytest

from core.models.drawing import Drawing, LineElement, PolylineElement, TextElement
from core.parser.pdf_parser import PdfParser
from core.analyzer.dimension_check import (
    DimensionCheck,
    calibrate_scale_from_dimension,
    check_dimensions,
    parse_dimension_value,
    rescale_drawing,
)


def _make_two_room_pdf(path: str) -> None:
    """部屋1（寸法通り）と部屋2（寸法に対して 2% ずれ）の合成 PDF。"""
    doc = pymupdf.open()
    page = doc.new_page(width=1200, height=900)
    page.draw_rect(pymupdf.Rect(100, 100, 500, 400), color=(0, 0, 0), fill=None, width=1)
    page.draw_line(pymupdf.Point(100, 450), pymupdf.Point(500, 450), color=(0, 0, 0), width=0.5)
    page.draw_line(pymupdf.Point(100, 400), pymupdf.Point(100, 460), color=(0, 0, 0), width=0.5)
    page.draw_line(pymupdf.Point(500, 400), pymupdf.Point(500, 460), color=(0, 0, 0), width=0.5)
    page.insert_text((280, 440), "4000", fontsize=12)
    page.draw_rect(pymupdf.Rect(600, 100, 804, 400), color=(0, 0, 0), fill=None, width=1)
    page.draw_line(pymupdf.Point(600, 450), pymupdf.Point(804, 450), color=(0, 0, 0), width=0.5)
    page.draw_line(pymupdf.Point(600, 400), pymupdf.Point(600, 460), color=(0, 0, 0), width=0.5)
    page.draw_line(pymupdf.Point(804, 400), pymupdf.Point(804, 460), color=(0, 0, 0), width=0.5)
    page.insert_text((660, 440), "2000", fontsize=12)
    doc.save(path)
    doc.close()


def _make_single_room_pdf(path: str, width_pt: float, dim_text: str) -> None:
    """1 部屋だけの合成 PDF。幅 width_pt に対して寸法 dim_text を付ける。"""
    doc = pymupdf.open()
    page = doc.new_page(width=1200, height=900)
    page.draw_rect(pymupdf.Rect(100, 100, 100 + width_pt, 400), color=(0, 0, 0), fill=None, width=1)
    page.draw_line(pymupdf.Point(100, 450), pymupdf.Point(100 + width_pt, 450), color=(0, 0, 0), width=0.5)
    page.draw_line(pymupdf.Point(100, 400), pymupdf.Point(100, 460), color=(0, 0, 0), width=0.5)
    page.draw_line(pymupdf.Point(100 + width_pt, 400), pymupdf.Point(100 + width_pt, 460), color=(0, 0, 0), width=0.5)
    page.insert_text((280, 440), dim_text, fontsize=12)
    doc.save(path)
    doc.close()


def _make_manual_drawing(measured_length_mm: float, value_mm: float) -> Drawing:
    """寸法線・引出線・測定対象の線を直接組み立てた Drawing。

    寸法線 (0,100)-(1000,100)、引出線は両端に (x,0)-(x,150)、
    測定対象の線は (0,0)-(measured_length_mm,0)、
    寸法テキストは寸法線のすぐ上に置く。
    """
    drawing = Drawing(
        drawing_id="manual", file_name="manual", file_type="pdf",
        scale=10.0, units="mm", elements=[],
    )
    drawing._meta = {"mm_per_pt": 10.0}
    counter = [0]

    def _line(start, end):
        counter[0] += 1
        return LineElement(
            element_id=f"L{counter[0]:03d}", element_type="LINE",
            start=list(start), end=list(end),
        )

    def _text(text, bbox):
        counter[0] += 1
        return TextElement(
            element_id=f"T{counter[0]:03d}", element_type="TEXT",
            text=text, insertion_point=[bbox[0], bbox[3]],
            height=10.0, bbox=list(bbox),
        )

    drawing.elements = [
        _line((0, 100), (1000, 100)),
        _line((0, 0), (0, 150)),
        _line((1000, 0), (1000, 150)),
        _line((0, 0), (measured_length_mm, 0)),
        _text(str(int(value_mm)), (450, 105, 550, 125)),
    ]
    return drawing


def test_parse_dimension_value():
    assert parse_dimension_value("4000") == 4000.0
    assert parse_dimension_value("3,600") == 3600.0
    assert parse_dimension_value("1200.5") == 1200.5
    assert parse_dimension_value("４０００") == 4000.0
    assert parse_dimension_value("4000mm") == 4000.0
    assert parse_dimension_value("  2,400  ") == 2400.0
    assert parse_dimension_value("会議室") is None
    assert parse_dimension_value("101号室") is None
    assert parse_dimension_value("") is None
    assert parse_dimension_value("0") is None
    assert parse_dimension_value("-100") is None
    assert parse_dimension_value("12a") is None


def test_check_dimensions_matched_and_mismatched(tmp_path):
    pdf_path = os.path.join(tmp_path, "two_rooms.pdf")
    _make_two_room_pdf(pdf_path)
    drawing = PdfParser().parse(pdf_path, scale_mm_per_pt=10.0)

    checks = check_dimensions(drawing)

    assert len(checks) == 2
    by_text = {c.dimension_text: c for c in checks}
    matched = by_text["4000"]
    assert matched.status == "matched"
    assert matched.value_mm == 4000.0
    assert matched.measured_mm == pytest.approx(4000.0)
    assert matched.measured_length_pt == pytest.approx(400.0)
    assert matched.difference_mm == pytest.approx(0.0)
    assert matched.confidence >= 0.75
    mismatched = by_text["2000"]
    assert mismatched.status == "mismatched"
    assert mismatched.value_mm == 2000.0
    assert mismatched.measured_mm == pytest.approx(2040.0)
    assert mismatched.difference_mm == pytest.approx(40.0)
    assert mismatched.tolerance_mm == pytest.approx(10.0)
    assert mismatched.confidence >= 0.75


def test_check_results_are_recorded_in_meta(tmp_path):
    pdf_path = os.path.join(tmp_path, "two_rooms.pdf")
    _make_two_room_pdf(pdf_path)
    drawing = PdfParser().parse(pdf_path, scale_mm_per_pt=10.0)

    checks = check_dimensions(drawing)

    recorded = drawing._meta["dimension_checks"]
    assert len(recorded) == 2
    assert [r["status"] for r in recorded] == [c.status for c in checks]
    assert recorded[0]["dimension_text"] == "4000"


def test_numeric_room_number_is_not_a_dimension(tmp_path):
    pdf_path = os.path.join(tmp_path, "two_rooms.pdf")
    _make_two_room_pdf(pdf_path)
    drawing = PdfParser().parse(pdf_path, scale_mm_per_pt=10.0)
    # 部屋番号らしい数値テキストを部屋1の内側に追加する。
    drawing.elements.append(TextElement(
        element_id="T999", element_type="TEXT", text="101",
        insertion_point=[2500.0, 6500.0], height=120.0,
        bbox=[2500.0, 6440.0, 2620.0, 6560.0],
    ))

    checks = check_dimensions(drawing)

    assert [c.dimension_text for c in checks] == ["4000", "2000"]


def test_single_extension_line_is_to_confirm(tmp_path):
    pdf_path = os.path.join(tmp_path, "one_ext.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=1200, height=900)
    page.draw_rect(pymupdf.Rect(100, 100, 500, 400), color=(0, 0, 0), fill=None, width=1)
    page.draw_line(pymupdf.Point(100, 450), pymupdf.Point(500, 450), color=(0, 0, 0), width=0.5)
    # 引出線は左端のみ。
    page.draw_line(pymupdf.Point(100, 400), pymupdf.Point(100, 460), color=(0, 0, 0), width=0.5)
    page.insert_text((280, 440), "4000", fontsize=12)
    doc.save(pdf_path)
    doc.close()
    drawing = PdfParser().parse(pdf_path, scale_mm_per_pt=10.0)

    checks = check_dimensions(drawing)

    assert len(checks) == 1
    assert checks[0].status == "to_confirm"
    assert checks[0].confidence < 0.75
    # 測定自体はできているが、確信度が低いので確定しない。
    assert checks[0].measured_mm == pytest.approx(4000.0)


def test_no_measured_line_is_not_determinable(tmp_path):
    pdf_path = os.path.join(tmp_path, "no_target.pdf")
    doc = pymupdf.open()
    page = doc.new_page(width=1200, height=900)
    # 寸法線と引出線だけ。測定対象の線はない。
    page.draw_line(pymupdf.Point(100, 450), pymupdf.Point(500, 450), color=(0, 0, 0), width=0.5)
    page.draw_line(pymupdf.Point(100, 400), pymupdf.Point(100, 460), color=(0, 0, 0), width=0.5)
    page.draw_line(pymupdf.Point(500, 400), pymupdf.Point(500, 460), color=(0, 0, 0), width=0.5)
    page.insert_text((280, 440), "4000", fontsize=12)
    doc.save(pdf_path)
    doc.close()
    drawing = PdfParser().parse(pdf_path, scale_mm_per_pt=10.0)

    checks = check_dimensions(drawing)

    assert len(checks) == 1
    assert checks[0].status == "not_determinable"
    assert checks[0].measured_mm is None


def test_tolerance_boundary_is_matched():
    # 差がちょうど許容誤差（0.5%）なら一致。
    drawing = _make_manual_drawing(measured_length_mm=1005.0, value_mm=1000.0)
    checks = check_dimensions(drawing)
    assert len(checks) == 1
    assert checks[0].status == "matched"
    assert checks[0].difference_mm == pytest.approx(5.0)
    assert checks[0].tolerance_mm == pytest.approx(5.0)


def test_just_over_tolerance_is_mismatched():
    # 差が許容誤差（0.5%）をわずかに超えれば不一致。
    drawing = _make_manual_drawing(measured_length_mm=1006.0, value_mm=1000.0)
    checks = check_dimensions(drawing)
    assert len(checks) == 1
    assert checks[0].status == "mismatched"
    assert checks[0].difference_mm == pytest.approx(6.0)


def test_calibrate_and_rescale_makes_dimensions_match(tmp_path):
    pdf_path = os.path.join(tmp_path, "off_by_2pct.pdf")
    # 寸法 4000 に対して 408pt（4080mm 相当）で描いた図面。
    _make_single_room_pdf(pdf_path, width_pt=408.0, dim_text="4000")
    drawing = PdfParser().parse(pdf_path, scale_mm_per_pt=10.0)

    checks = check_dimensions(drawing)
    assert len(checks) == 1
    assert checks[0].status == "mismatched"
    assert checks[0].measured_mm == pytest.approx(4080.0)

    new_mm_per_pt = calibrate_scale_from_dimension(checks[0], 10.0)
    assert new_mm_per_pt == pytest.approx(4000.0 / 408.0)
    factor = rescale_drawing(drawing, new_mm_per_pt, source_check=checks[0])
    assert factor == pytest.approx(4000.0 / 4080.0)
    assert drawing.scale == pytest.approx(4000.0 / 408.0)
    assert drawing._meta["mm_per_pt"] == pytest.approx(4000.0 / 408.0)
    assert drawing._meta["units_source"] == "calibrated_from_dimension"
    assert drawing._meta["calibration"]["dimension_id"] == checks[0].dimension_id
    assert drawing._meta["calibration"]["value_mm"] == 4000.0
    # 調整前の照合結果は古くなったため削除されている。
    assert drawing._meta["dimension_checks"] == []

    # 調整後に照合し直すと一致する。
    rechecks = check_dimensions(drawing)
    assert len(rechecks) == 1
    assert rechecks[0].status == "matched"
    assert rechecks[0].measured_mm == pytest.approx(4000.0)
    # 部屋の幅も寸法通りの 4000mm になっている。
    room = next(e for e in drawing.elements if isinstance(e, PolylineElement))
    width = room.points[1][0] - room.points[0][0]
    assert width == pytest.approx(4000.0)


def test_calibrate_without_measured_line_raises():
    check = DimensionCheck(
        dimension_id="DIM001", value_mm=4000.0, dimension_text="4000",
        status="not_determinable", confidence=0.85, measured_length_pt=None,
    )
    with pytest.raises(ValueError):
        calibrate_scale_from_dimension(check, 10.0)


def test_rescale_with_invalid_factor_raises(tmp_path):
    pdf_path = os.path.join(tmp_path, "room.pdf")
    _make_single_room_pdf(pdf_path, width_pt=400.0, dim_text="4000")
    drawing = PdfParser().parse(pdf_path, scale_mm_per_pt=10.0)
    with pytest.raises(ValueError):
        rescale_drawing(drawing, 0.0)
    with pytest.raises(ValueError):
        rescale_drawing(drawing, -5.0)
