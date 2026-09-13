import pytest
from core.models.drawing import Drawing, LineElement, TextElement
from core.models.room import Room
from core.models.change import Change
from core.models.ocr_result import OCRResult

def test_drawing_serialization():
    # テスト用要素の作成
    line = LineElement(
        element_id="L001",
        element_type="LINE",
        layer="WALL",
        color=1,
        start=[0.0, 0.0],
        end=[3000.0, 4000.0]
    )
    
    text = TextElement(
        element_id="T001",
        element_type="TEXT",
        layer="ROOM_NAME",
        text="会議室",
        insertion_point=[1500.0, 2000.0]
    )
    
    drawing = Drawing(
        drawing_id="A-101",
        file_name="A-101.dxf",
        file_type="dxf",
        scale=100.0,
        units="mm",
        elements=[line, text]
    )
    
    # 辞書シリアライズ
    data = drawing.to_dict()
    assert data["drawing_id"] == "A-101"
    assert len(data["elements"]) == 2
    assert data["elements"][0]["element_type"] == "LINE"
    assert data["elements"][1]["element_type"] == "TEXT"
    
    # 辞書デシリアライズ
    loaded = Drawing.from_dict(data)
    assert loaded.drawing_id == "A-101"
    assert len(loaded.elements) == 2
    assert isinstance(loaded.elements[0], LineElement)
    assert isinstance(loaded.elements[1], TextElement)
    assert loaded.elements[0].start == [0.0, 0.0]
    assert loaded.elements[1].text == "会議室"

def test_room_model():
    room = Room(
        room_id="R001",
        room_name="事務室",
        area_m2=24.5,
        boundary=[[0.0, 0.0], [5000.0, 0.0], [5000.0, 5000.0], [0.0, 5000.0]],
        confidence=0.98,
        properties={"ceiling_height": 2700.0, "occupants": 10, "required_ventilation": 200.0}
    )
    
    data = room.to_dict()
    assert data["room_id"] == "R001"
    assert data["properties"]["ceiling_height"] == 2700.0
    
    loaded = Room.from_dict(data)
    assert loaded.room_name == "事務室"
    assert loaded.ceiling_height == 2700.0
    assert loaded.occupants == 10
    assert loaded.required_ventilation == 200.0

def test_change_model():
    change = Change(
        change_id="C001",
        type="wall_moved",
        location=[1000.0, 2000.0, 1500.0, 2500.0],
        old_data={"start": [1000.0, 2000.0]},
        new_data={"start": [1200.0, 2000.0]},
        confidence=0.95
    )
    
    data = change.to_dict()
    assert data["type"] == "wall_moved"
    
    loaded = Change.from_dict(data)
    assert loaded.change_id == "C001"
    assert loaded.old_data["start"] == [1000.0, 2000.0]

def test_ocr_result_model():
    res = OCRResult(
        text="休憩室",
        bbox=[100, 200, 200, 250],
        confidence=0.93
    )
    
    data = res.to_dict()
    assert data["text"] == "休憩室"
    
    loaded = OCRResult.from_dict(data)
    assert loaded.text == "休憩室"
