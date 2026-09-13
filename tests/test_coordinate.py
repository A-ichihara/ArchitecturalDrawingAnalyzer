import pytest
from core.coordinate.transformer import CoordinateTransformer

def test_cad_transformer():
    # CAD: 縮尺1/100, 単位"mm"
    trans = CoordinateTransformer.from_cad(scale=100.0, units="mm")
    
    pt = [10.0, 20.0]
    common_pt = trans.transform(pt)
    # 共通座標系 (mm) = CAD座標 * 100
    assert common_pt == [1000.0, 2000.0]
    
    # 逆変換して元に戻るか検証
    orig_pt = trans.inverse_transform(common_pt)
    assert orig_pt == [10.0, 20.0]

    # CAD: 縮尺1/50, 単位"m", 平行移動 offset_x=10, offset_y=20
    trans_m = CoordinateTransformer.from_cad(scale=50.0, offset_x=10.0, offset_y=20.0, units="m")
    # 共通座標系 (mm) = (CAD座標 * 1000 * 50) + offset
    # 1.0 m -> 1.0 * 1000 * 50 + 10 = 50010 mm
    # 2.0 m -> 2.0 * 1000 * 50 + 20 = 100020 mm
    common_pt_m = trans_m.transform([1.0, 2.0])
    assert common_pt_m == [50010.0, 100020.0]
    
    assert trans_m.inverse_transform(common_pt_m) == [1.0, 2.0]

def test_pdf_transformer():
    # PDF: ページ高 800pt, 縮尺 100倍, dpi 72, 原点 top_left
    # 1pt = 25.4 / 72 = 0.352777... mm -> 縮尺100で 1pt = 35.2777... mm
    trans = CoordinateTransformer.from_pdf(page_height_pt=800.0, scale=100.0, dpi=72.0, origin="top_left")
    
    # 左上原点 (0,0) -> 共通座標系の左下原点に換算すると Y は最大値になる
    # Y = 800pt * 35.2777... = 28222.222... mm
    common_pt = trans.transform([0.0, 0.0])
    assert common_pt[0] == 0.0
    assert pytest.approx(common_pt[1]) == 800.0 * (25.4 / 72.0) * 100.0
    
    # 相互変換の一貫性をテスト
    pt = [150.0, 200.0]
    common_pt = trans.transform(pt)
    orig_pt = trans.inverse_transform(common_pt)
    assert pytest.approx(orig_pt[0]) == 150.0
    assert pytest.approx(orig_pt[1]) == 200.0

def test_image_transformer():
    # 画像: 解像度 300 dpi, 縮尺 100倍, 画像高 3000px
    # 1px = 25.4 / 300 = 0.08466... mm -> 縮尺100倍で 8.466... mm
    trans = CoordinateTransformer.from_image(dpi=300.0, scale=100.0, image_height_px=3000.0)
    
    pt = [500.0, 800.0]
    common_pt = trans.transform(pt)
    orig_pt = trans.inverse_transform(common_pt)
    
    assert pytest.approx(orig_pt[0]) == 500.0
    assert pytest.approx(orig_pt[1]) == 800.0
