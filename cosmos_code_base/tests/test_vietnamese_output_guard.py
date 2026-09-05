from src.result_utils import contains_cjk, normalize_segment, replace_cjk_content


def test_detects_chinese_text_recursively() -> None:
    assert contains_cjk({"description": "室内场景", "actions": []})
    assert not contains_cjk({"description": "Nhân viên đang làm việc.", "actions": ["ngồi"]})


def test_replaces_chinese_prose_but_preserves_detections() -> None:
    source = {
        "description": "室内有多个办公桌",
        "people_count": 7,
        "phone_detected": False,
        "crowd_detected": True,
        "objects": ["电脑", "bàn làm việc"],
        "actions": ["工作"],
        "scene_changes": "没有变化",
        "abnormal": True,
        "abnormal_type": "crowding",
        "risk_level": "low",
        "important_event": {"has_event": True, "event": "多人聚集", "timestamp": "00:00:00"},
        "confidence": 0.8,
    }

    cleaned = replace_cjk_content(source, "00:00:00", "00:01:30")
    segment = normalize_segment(cleaned, "00:00:00", "00:01:30")

    assert not contains_cjk(segment)
    assert segment["people_count"] == 7
    assert segment["crowd_detected"] is True
    assert segment["objects"] == ["bàn làm việc"]
    assert "7 người" in segment["description"]
