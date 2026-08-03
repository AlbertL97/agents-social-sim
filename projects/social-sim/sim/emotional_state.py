"""Parse and validate the emotional-state JSON snapshot.

After each entity turn the GM resolution returns a single structured JSON object
(folding event resolution + emotional extraction into ONE model call to conserve
budget, per the project brief). This module validates/normalizes that object
into the shapes stored in ``entity_state`` and ``sim_turn_log``.

Emotional snapshot schema:
    {
      "mood": "<short phrase>",
      "stress": "low" | "medium" | "high",
      "stances": {"<other_entity_name>": "<one-line stance phrase>", ...}
    }
"""

from __future__ import annotations

import json
import re
from typing import Any

from sim.personas import VALID_STRESS, normalize_stress

VALID_TRIGGER_TYPES = {"responds_to", "procedural", "opening", "internal"}


class EmotionParseError(ValueError):
    """Raised when the emotional snapshot cannot be parsed/validated."""


def _extract_json_object(text: str) -> str:
    """Pull the first ``{...}`` substring out of a (possibly noisy) model reply."""
    text = text.strip()
    # Strip Markdown code fences if present.
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    if start == -1:
        return text
    # Find the matching closing brace (naive but adequate for our shape).
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def parse_snapshot(raw: str | dict[str, Any]) -> dict[str, Any]:
    """Parse + validate an emotional snapshot into a normalized dict.

    Accepts a JSON string (possibly wrapped in prose/code fences) or a dict.
    Returns ``{"mood": str, "stress": str, "stances": {name: str}}``.
    Raises ``EmotionParseError`` on hard failure.
    """
    if isinstance(raw, dict):
        obj = raw
    else:
        try:
            obj = json.loads(_extract_json_object(str(raw)))
        except json.JSONDecodeError as exc:
            raise EmotionParseError(f"not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise EmotionParseError("snapshot must be a JSON object")

    mood = str(obj.get("mood", "")).strip()
    if not mood:
        raise EmotionParseError("snapshot missing 'mood'")

    stress = normalize_stress(str(obj.get("stress", "medium")))
    if stress not in VALID_STRESS:
        stress = "medium"

    raw_stances = obj.get("stances", {})
    if not isinstance(raw_stances, dict):
        raise EmotionParseError("'stances' must be an object")
    stances = {
        str(k).strip(): str(v).strip()
        for k, v in raw_stances.items()
        if str(k).strip() and str(v).strip()
    }
    if not stances:
        raise EmotionParseError("snapshot has no stances")

    return {"mood": mood, "stress": stress, "stances": stances}


def parse_resolution(raw: str | dict[str, Any]) -> dict[str, Any]:
    """Parse the full GM resolution object and validate its parts.

    Expected shape:
        {
          "resolved_event": str,
          "trigger": str | {"type": str, "ref": str},
          "state_change": {entity_name: description, ...},
          "emotion_snapshot": {mood, stress, stances}
        }
    """
    if isinstance(raw, dict):
        obj = raw
    else:
        try:
            obj = json.loads(_extract_json_object(str(raw)))
        except json.JSONDecodeError as exc:
            raise EmotionParseError(f"resolution not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise EmotionParseError("resolution must be a JSON object")

    resolved_event = str(obj.get("resolved_event", "")).strip()
    if not resolved_event:
        raise EmotionParseError("resolution missing 'resolved_event'")

    snapshot = parse_snapshot(obj.get("emotion_snapshot", {}))

    trigger = obj.get("trigger", "")
    trigger = _normalize_trigger(trigger)

    raw_change = obj.get("state_change", {}) or {}
    state_change = {
        str(k).strip(): str(v).strip()
        for k, v in (raw_change.items() if isinstance(raw_change, dict) else [])
        if str(k).strip() and str(v).strip()
    }

    return {
        "resolved_event": resolved_event,
        "trigger": trigger,
        "state_change": state_change,
        "emotion_snapshot": snapshot,
    }


def _normalize_trigger(trigger: Any) -> dict[str, str]:
    """Normalize a trigger into {"type": ..., "ref": ...}."""
    if isinstance(trigger, dict):
        ttype = str(trigger.get("type", "responds_to")).strip()
        ref = str(trigger.get("ref", "")).strip()
        if not ref:
            ref = str(trigger.get("utterance", "") or trigger.get("to", "")).strip()
        if ttype not in VALID_TRIGGER_TYPES:
            ttype = "responds_to"
        return {"type": ttype, "ref": ref}
    text = str(trigger).strip()
    return {"type": "responds_to", "ref": text} if text else {
        "type": "opening",
        "ref": "",
    }
