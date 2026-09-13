"""
tests/create_test_dxf.py
テスト用のDXFファイルを ezdxf API で生成するスクリプト。
tests/data/ フォルダにテスト用DXFを出力する。

実行方法:
    python tests/create_test_dxf.py
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
from ezdxf import colors


def ensure_data_dir() -> str:
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def create_test01_simple_rect(output_dir: str) -> None:
    """Test 01: 単純な矩形（LINE 4本）"""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # 5000 x 3000 mm の矩形
    msp.add_line((0, 0), (5000, 0))
    msp.add_line((5000, 0), (5000, 3000))
    msp.add_line((5000, 3000), (0, 3000))
    msp.add_line((0, 3000), (0, 0))

    path = os.path.join(output_dir, "test01_simple_rect.dxf")
    doc.saveas(path)
    print(f"生成: {path}")


def create_test02_multiple_rects(output_dir: str) -> None:
    """Test 02: 複数の矩形（部屋レイアウトを模擬）"""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # レイヤー設定
    doc.layers.add("WALL", color=7)
    doc.layers.add("ROOM_NAME", color=2)

    def add_rect(x, y, w, h, layer="WALL"):
        msp.add_line((x, y), (x+w, y), dxfattribs={"layer": layer})
        msp.add_line((x+w, y), (x+w, y+h), dxfattribs={"layer": layer})
        msp.add_line((x+w, y+h), (x, y+h), dxfattribs={"layer": layer})
        msp.add_line((x, y+h), (x, y), dxfattribs={"layer": layer})

    # 3部屋レイアウト
    add_rect(0, 0, 5000, 4000)      # 事務室
    add_rect(5000, 0, 3000, 4000)   # 会議室
    add_rect(8000, 0, 2000, 4000)   # 廊下

    # 部屋名テキスト
    msp.add_text("事務室", dxfattribs={"insert": (2000, 2000), "height": 250, "layer": "ROOM_NAME"})
    msp.add_text("会議室", dxfattribs={"insert": (6000, 2000), "height": 250, "layer": "ROOM_NAME"})
    msp.add_text("廊下", dxfattribs={"insert": (8500, 2000), "height": 250, "layer": "ROOM_NAME"})

    path = os.path.join(output_dir, "test02_multiple_rects.dxf")
    doc.saveas(path)
    print(f"生成: {path}")


def create_test03_lwpolyline(output_dir: str) -> None:
    """Test 03: LINE + LWPOLYLINE の組み合わせ"""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # LWPOLYLINE（閉じた矩形）
    msp.add_lwpolyline(
        [(0, 0), (6000, 0), (6000, 4000), (0, 4000)],
        close=True,
        dxfattribs={"layer": "WALL", "color": 3},
    )

    # 内部を仕切るLINE
    msp.add_line((3000, 0), (3000, 4000), dxfattribs={"layer": "WALL", "color": 7})

    # ARC（ドア記号）
    msp.add_arc(center=(3000, 0), radius=800, start_angle=0, end_angle=90,
                dxfattribs={"layer": "DOOR"})

    # CIRCLE（柱記号）
    msp.add_circle(center=(500, 3500), radius=150, dxfattribs={"layer": "COLUMN", "color": 5})
    msp.add_circle(center=(5500, 3500), radius=150, dxfattribs={"layer": "COLUMN", "color": 5})

    path = os.path.join(output_dir, "test03_lwpolyline.dxf")
    doc.saveas(path)
    print(f"生成: {path}")


def create_test04_text(output_dir: str) -> None:
    """Test 04: テキスト要素の確認"""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # 外壁
    msp.add_lwpolyline(
        [(0, 0), (10000, 0), (10000, 8000), (0, 8000)],
        close=True,
        dxfattribs={"layer": "WALL"},
    )

    # TEXT 要素
    texts = [
        ("事務室", 4000, 6000, 300),
        ("会議室 A", 4000, 4000, 300),
        ("WC", 4000, 2000, 300),
        ("A=25.5㎡", 4000, 5000, 200),
        ("A=18.3㎡", 4000, 3000, 200),
    ]
    for text, x, y, h in texts:
        msp.add_text(
            text,
            dxfattribs={"insert": (x, y), "height": h, "layer": "ROOM_NAME", "color": 2},
        )

    path = os.path.join(output_dir, "test04_text.dxf")
    doc.saveas(path)
    print(f"生成: {path}")


if __name__ == "__main__":
    data_dir = ensure_data_dir()
    create_test01_simple_rect(data_dir)
    create_test02_multiple_rects(data_dir)
    create_test03_lwpolyline(data_dir)
    create_test04_text(data_dir)
    print("\nテスト用DXFファイルの生成が完了しました。")
    print(f"出力先: {data_dir}")
