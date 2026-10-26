import os
import ezdxf

def _new_mm_document():
    """mm単位の図面ドキュメントを作る。

    ezdxf.new() の既定テンプレートは $INSUNITS=6（メートル）のため、
    mm桁の座標と組み合わせると面積が100万倍に誤算出される。
    サンプル図面はすべて mm 座標で描くので、単位を明示する。
    """
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4  # mm
    return doc

def ensure_data_dir() -> str:
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir

def create_sample_01_rect(data_dir: str):
    """Test 01: 矩形 (LWPOLYLINE)"""
    doc = _new_mm_document()
    msp = doc.modelspace()
    doc.layers.add("WALL", color=1)  # 赤
    
    # 5000 x 3000 mm の矩形
    points = [(0, 0), (5000, 0), (5000, 3000), (0, 3000)]
    poly = msp.add_lwpolyline(points, dxfattribs={"layer": "WALL"})
    poly.close(True)
    
    filepath = os.path.join(data_dir, "sample_01_rect.dxf")
    doc.saveas(filepath)
    print(f"Created: {filepath}")

def create_sample_02_multi_rect(data_dir: str):
    """Test 02: 複数の矩形"""
    doc = _new_mm_document()
    msp = doc.modelspace()
    doc.layers.add("ROOM_A", color=2)  # 黄
    doc.layers.add("ROOM_B", color=3)  # 緑
    
    # 部屋A (0, 0) - (4000, 3000)
    p1 = msp.add_lwpolyline([(0, 0), (4000, 0), (4000, 3000), (0, 3000)], dxfattribs={"layer": "ROOM_A"})
    p1.close(True)
    
    # 部屋B (4000, 0) - (8000, 3000)
    p2 = msp.add_lwpolyline([(4000, 0), (8000, 0), (8000, 3000), (4000, 3000)], dxfattribs={"layer": "ROOM_B"})
    p2.close(True)
    
    filepath = os.path.join(data_dir, "sample_02_multi_rect.dxf")
    doc.saveas(filepath)
    print(f"Created: {filepath}")

def create_sample_03_lines_arcs(data_dir: str):
    """Test 03: LINE + LWPOLYLINE + ARC + CIRCLE"""
    doc = _new_mm_document()
    msp = doc.modelspace()
    doc.layers.add("STRUCTURE", color=4)  # シアン
    doc.layers.add("FURNITURE", color=5)  # 青
    
    # LINE
    msp.add_line((0, 0), (10000, 0), dxfattribs={"layer": "STRUCTURE"})
    msp.add_line((10000, 0), (10000, 6000), dxfattribs={"layer": "STRUCTURE"})
    
    # LWPOLYLINE
    msp.add_lwpolyline([(0, 0), (0, 6000), (10000, 6000)], dxfattribs={"layer": "STRUCTURE"})
    
    # CIRCLE (柱や円形テーブル等)
    msp.add_circle(center=(2000, 2000), radius=500, dxfattribs={"layer": "FURNITURE"})
    
    # ARC (ドア開口部等)
    msp.add_arc(center=(4000, 0), radius=1000, start_angle=0, end_angle=90, dxfattribs={"layer": "STRUCTURE"})
    
    filepath = os.path.join(data_dir, "sample_03_lines_arcs.dxf")
    doc.saveas(filepath)
    print(f"Created: {filepath}")

def create_sample_04_text(data_dir: str):
    """Test 04: 文字 (TEXT / MTEXT)"""
    doc = _new_mm_document()
    msp = doc.modelspace()
    doc.layers.add("TEXT_LAYER", color=7)  # 白
    
    # TEXT
    msp.add_text("会議室 (ROOM 101)", dxfattribs={"height": 250, "insert": (500, 1500), "layer": "TEXT_LAYER"})
    
    # MTEXT
    msp.add_mtext("事務室\n面積: 45.0m2", dxfattribs={"char_height": 200, "insert": (3000, 1500), "layer": "TEXT_LAYER"})
    
    filepath = os.path.join(data_dir, "sample_04_text.dxf")
    doc.saveas(filepath)
    print(f"Created: {filepath}")

def main():
    data_dir = ensure_data_dir()
    create_sample_01_rect(data_dir)
    create_sample_02_multi_rect(data_dir)
    create_sample_03_lines_arcs(data_dir)
    create_sample_04_text(data_dir)
    print("All sample DXF files created successfully.")

if __name__ == "__main__":
    main()
