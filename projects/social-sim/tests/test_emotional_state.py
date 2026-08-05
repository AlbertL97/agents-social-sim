"""Tests: emotional-state / resolution JSON parsing and validation."""

import pytest

from sim.emotional_state import EmotionParseError, parse_resolution, parse_snapshot


def test_parse_snapshot_valid():
    snap = parse_snapshot(
        {"mood": "wary", "stress": "high", "stances": {"Tobias": "wants respect"}}
    )
    assert snap["mood"] == "wary"
    assert snap["stress"] == "high"
    assert snap["stances"]["Tobias"] == "wants respect"


def test_parse_snapshot_from_json_string_with_prose():
    raw = (
        'Here is the snapshot:\n```json\n'
        '{"mood": "calm", "stress": "low", "stances": {"Mira": "ally"}}\n```\n'
    )
    snap = parse_snapshot(raw)
    assert snap["mood"] == "calm"
    assert snap["stress"] == "low"


def test_parse_snapshot_normalizes_stress():
    assert parse_snapshot({"mood": "x", "stress": "medium-high", "stances": {"A": "b"}})["stress"] == "high"
    assert parse_snapshot({"mood": "x", "stress": "low-medium", "stances": {"A": "b"}})["stress"] == "low"


def test_parse_snapshot_rejects_missing_mood():
    with pytest.raises(EmotionParseError):
        parse_snapshot({"stress": "low", "stances": {"A": "b"}})


def test_parse_snapshot_rejects_no_stances():
    with pytest.raises(EmotionParseError):
        parse_snapshot({"mood": "x", "stress": "low", "stances": {}})


def test_parse_snapshot_rejects_garbage():
    with pytest.raises(EmotionParseError):
        parse_snapshot("this is not json at all { ")


def test_parse_resolution_full():
    obj = {
        "resolved_event": "Renata asked to slow down.",
        "trigger": {"type": "responds_to", "ref": "Tobias's push"},
        "state_change": {"Tobias": "slightly more guarded"},
        "emotion_snapshot": {
            "mood": "cautious", "stress": "medium",
            "stances": {"Tobias": "wants respect", "Mira": "ally", "Leo": "shield"},
        },
    }
    res = parse_resolution(obj)
    assert res["resolved_event"] == "Renata asked to slow down."
    assert res["trigger"]["type"] == "responds_to"
    assert res["state_change"]["Tobias"].startswith("slightly")
    assert res["emotion_snapshot"]["stress"] == "medium"
    assert len(res["emotion_snapshot"]["stances"]) == 3


def test_parse_resolution_normalizes_string_trigger():
    res = parse_resolution(
        {"resolved_event": "x", "trigger": "the prior utterance",
         "emotion_snapshot": {"mood": "m", "stress": "low", "stances": {"A": "b"}}}
    )
    assert res["trigger"] == {"type": "responds_to", "ref": "the prior utterance"}


def test_parse_resolution_rejects_missing_event():
    with pytest.raises(EmotionParseError):
        parse_resolution({"emotion_snapshot": {"mood": "m", "stress": "low", "stances": {"A": "b"}}})
