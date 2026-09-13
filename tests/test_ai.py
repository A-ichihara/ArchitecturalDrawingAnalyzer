import pytest
from core.ai.interface import IAiEngine, NullAiEngine, LocalAiEngine

def test_ai_engines_instantiation():
    null_ai = NullAiEngine()
    local_ai = LocalAiEngine()
    
    assert isinstance(null_ai, IAiEngine)
    assert isinstance(local_ai, IAiEngine)

def test_null_ai_engine_behavior():
    ai = NullAiEngine()
    assert ai.is_enabled() is False
    
    # ルールベースによる部屋名補正・標準化機能のテスト
    res_meet = ai.classify_room_name("ミーティングルーム A")
    assert res_meet["standard_name"] == "会議室"
    assert res_meet["confidence"] == 1.0
    
    res_wc = ai.classify_room_name("男子WC")
    assert res_wc["standard_name"] == "便所"
    
    res_office = ai.classify_room_name("第2オフィス")
    assert res_office["standard_name"] == "事務室"
    
    # マッピングにない部屋名はそのまま返す
    res_other = ai.classify_room_name("電気室")
    assert res_other["standard_name"] == "電気室"
    
    # AI無効時の信頼度は常に1.0を返す
    assert ai.validate_analysis_confidence({}) == 1.0

def test_local_ai_engine_behavior():
    ai = LocalAiEngine()
    assert ai.is_enabled() is True
    
    # スタブとしての動作テスト
    res = ai.classify_room_name("オフィス")
    assert res["standard_name"] == "オフィス"
    assert res["confidence"] == 0.0
