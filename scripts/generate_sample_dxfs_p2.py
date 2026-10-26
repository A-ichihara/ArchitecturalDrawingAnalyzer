"""
scripts.generate_sample_dxfs_p2
Phase 2（構造解析・要素情報解析）検証用の複複雑・大量要素・多レイヤー DXF サンプルファイル生成スクリプト。
"""

import os
import random
import ezdxf


def generate_complex_sample_dxf(output_path: str) -> None:
    doc = ezdxf.new("R2010")
    # mm単位の図面。ezdxfの既定テンプレートは $INSUNITS=6（メートル）のため明示する。
    # これがないと mm 桁の座標がメートルと解釈され、面積が100万倍に誤算出される。
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()

    # 1. レイヤー定義（11層）
    layers = [
        ("GRID", 8),            # 通し芯 (グレー)
        ("WALL_OUTER", 7),      # 外壁 (白/黒)
        ("WALL_INNER", 2),      # 内壁 (黄)
        ("COLUMN", 1),          # 柱 (赤)
        ("WINDOW", 4),          # 窓 (シアン)
        ("DOOR", 3),            # 扉 (緑)
        ("ROOM_NAME", 6),       # 部屋名 (マゼンタ)
        ("DIMENSION", 5),       # 寸法 (青)
        ("EQUIPMENT", 9),       # 設備 (ライトグレー)
        ("FURNITURE", 2),       # 家具 (黄)
        ("TITLE_BLOCK", 7),     # 図枠 (白/黒)
    ]

    for name, color in layers:
        doc.layers.add(name=name, color=color)

    # 2. ブロック定義 (DOOR_SINGLE, COLUMN_RECT)
    door_block = doc.blocks.new(name="DOOR_SINGLE")
    door_block.add_line((0, 0), (0, 800), dxfattribs={"color": 3})
    door_block.add_arc((0, 0), 800, 0, 90, dxfattribs={"color": 3})

    col_block = doc.blocks.new(name="COLUMN_RECT")
    col_block.add_lwpolyline([(0, 0), (600, 0), (600, 600), (0, 600)], close=True, dxfattribs={"color": 1})

    # 3. 通し芯 (GRID)
    grid_x = [0, 4000, 8000, 12000, 16000, 20000]
    grid_y = [0, 4000, 8000, 12000, 16000]

    for x in grid_x:
        msp.add_line((x, -2000), (x, 18000), dxfattribs={"layer": "GRID"})
    for y in grid_y:
        msp.add_line((-2000, y), (22000, y), dxfattribs={"layer": "GRID"})

    # 4. 外壁 (WALL_OUTER)
    msp.add_lwpolyline(
        [(0, 0), (20000, 0), (20000, 16000), (0, 16000)],
        close=True,
        dxfattribs={"layer": "WALL_OUTER"}
    )

    # 5. 柱 (COLUMN) & INSERT
    for x in grid_x:
        for y in grid_y:
            msp.add_blockref("COLUMN_RECT", (x - 300, y - 300), dxfattribs={"layer": "COLUMN"})

    # 6. 内壁 (WALL_INNER)
    for y in [4000, 8000, 12000]:
        msp.add_line((0, y), (20000, y), dxfattribs={"layer": "WALL_INNER"})
    for x in [4000, 8000, 12000, 16000]:
        msp.add_line((x, 0), (x, 16000), dxfattribs={"layer": "WALL_INNER"})

    # 7. 扉 (INSERT)
    for x in [2000, 6000, 10000, 14000, 18000]:
        for y in [4000, 8000, 12000]:
            msp.add_blockref("DOOR_SINGLE", (x, y), dxfattribs={"layer": "DOOR"})

    # 8. 部屋名 (ROOM_NAME)
    rooms = [
        ("エントランスホール", 2000, 2000),
        ("事務室 A", 6000, 2000),
        ("事務室 B", 10000, 2000),
        ("会議室 1", 14000, 2000),
        ("会議室 2", 18000, 2000),
        ("廊下", 10000, 6000),
        ("執務室 1", 6000, 10000),
        ("執務室 2", 14000, 10000),
        ("役員室", 6000, 14000),
        ("応接室", 14000, 14000),
    ]
    for rname, rx, ry in rooms:
        msp.add_text(rname, dxfattribs={"layer": "ROOM_NAME", "height": 300, "insert": (rx, ry)})

    # 9. 大量要素生成 (FURNITURE / EQUIPMENT / DIMENSION で合計1000要素規模にする)
    random.seed(42)
    for i in range(300):
        fx = random.uniform(100, 19900)
        fy = random.uniform(100, 15900)
        msp.add_circle((fx, fy), radius=random.uniform(50, 300), dxfattribs={"layer": "EQUIPMENT"})

    for i in range(300):
        fx = random.uniform(100, 19900)
        fy = random.uniform(100, 15900)
        fw = random.uniform(200, 1000)
        fh = random.uniform(200, 1000)
        msp.add_lwpolyline([(fx, fy), (fx + fw, fy), (fx + fw, fy + fh), (fx, fy + fh)], close=True, dxfattribs={"layer": "FURNITURE"})

    for i in range(200):
        dx = random.uniform(100, 19900)
        dy = random.uniform(100, 15900)
        msp.add_arc((dx, dy), radius=random.uniform(100, 500), start_angle=0, end_angle=180, dxfattribs={"layer": "DIMENSION"})

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc.saveas(output_path)
    print(f"Phase 2 サンプルDXF生成完了: {output_path}")


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "..", "samples", "sample_p2_complex.dxf")
    generate_complex_sample_dxf(out)
