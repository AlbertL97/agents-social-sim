"""Persistence for the stateless cron-batch simulation.

Two interchangeable backends implement the same ``StateStore`` interface:

* **Supabase** (production, Free Postgres) — writes via the ``service_role``
  key; the read-only frontend uses the ``anon`` key under RLS.
* **Local JSON** (dry-run / tests / local dev) — used whenever
  ``SUPABASE_URL`` is unset, so the full pipeline runs with no network.

Four logical tables back the design (schema in ``supabase/schema.sql``):

* ``entity_state``   — one row per (scenario_id, entity_id). UPSERTed each turn;
                       drives the fast dashboard (mood, stress, stances, last
                       utterance).
* ``sim_turn_log``   — APPEND-ONLY research instrument (full utterance, trigger,
                       state_change, emotion_snapshot, model, raw_meta).
* ``sim_scenario``   — per-scenario reconstruction context: running summary,
                       turn count, persisted formative memories, initialized flag.
* ``sim_meta``       — daily request counter (resets at midnight Pacific, per
                       Gemini's RPD reset) + an ephemeral run-lock row with TTL.

The sim logs stored here are SEPARATE from the repo's ``research-logs/`` folder
and are never written there.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
    _PACIFIC = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover
    _PACIFIC = timezone.utc


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today_pacific_iso() -> str:
    return datetime.now(_PACIFIC).date().isoformat()


# ---------------------------------------------------------------------------
# Row dataclasses
# ---------------------------------------------------------------------------


@dataclass
class EntityStateRow:
    scenario_id: str
    entity_id: str
    mood: str
    stress: str
    stances: dict[str, str]
    last_utterance: str
    last_turn_ts: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TurnLogRow:
    scenario_id: str
    entity_id: str
    utterance: str
    trigger: dict[str, Any]
    state_change: dict[str, Any]
    emotion_snapshot: dict[str, Any]
    model: str
    raw_meta: dict[str, Any]
    turn_index: int
    ts: str = field(default_factory=now_utc_iso)
    turn_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScenarioStateRow:
    scenario_id: str
    running_summary: str
    turn_count: int
    formative_memories: dict[str, list[str]]
    initialized: bool
    updated_ts: str = field(default_factory=now_utc_iso)


# ---------------------------------------------------------------------------
# Store protocol
# ---------------------------------------------------------------------------


class StateStore(Protocol):
    # budget + lock
    def get_budget(self) -> tuple[str, int]: ...
    def set_budget(self, date: str, used: int) -> None: ...
    def acquire_run_lock(self, ttl_seconds: int) -> bool: ...
    def release_run_lock(self) -> None: ...

    # scenario reconstruction context
    def get_scenario_state(self, scenario_id: str) -> ScenarioStateRow | None: ...
    def upsert_scenario_state(self, row: ScenarioStateRow) -> None: ...

    # entity state (dashboard)
    def get_entity_states(self, scenario_id: str) -> list[EntityStateRow]: ...
    def upsert_entity_state(self, row: EntityStateRow) -> None: ...

    # append-only research log + transcript reconstruction
    def append_turn_log(self, row: TurnLogRow) -> None: ...
    def get_recent_turns(self, scenario_id: str, limit: int) -> list[TurnLogRow]: ...


# ---------------------------------------------------------------------------
# Local JSON backend
# ---------------------------------------------------------------------------


class LocalJSONStore:
    """File-backed store. All state lives under ``local_state_dir``.

    Layout:
        meta.json                      # {budget_date, used, running, running_since}
        scenarios/<id>.json            # ScenarioStateRow
        entity_state.json              # {scenario_id: {entity_id: EntityStateRow}}
        sim_turn_log.jsonl             # append-only, one TurnLogRow per line
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        (self.root / "scenarios").mkdir(parents=True, exist_ok=True)
        self._meta_path = self.root / "meta.json"
        self._entity_path = self.root / "entity_state.json"
        self._log_path = self.root / "sim_turn_log.jsonl"
        for p in (self._meta_path, self._entity_path):
            if not p.exists():
                p.write_text("{}", encoding="utf-8")
        if not self._log_path.exists():
            self._log_path.write_text("", encoding="utf-8")

    # -- meta / budget / lock ----------------------------------------------

    def _read_meta(self) -> dict[str, Any]:
        try:
            return json.loads(self._meta_path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def _write_meta(self, data: dict[str, Any]) -> None:
        tmp = self._meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, self._meta_path)

    def get_budget(self) -> tuple[str, int]:
        meta = self._read_meta()
        date = meta.get("budget_date") or today_pacific_iso()
        used = int(meta.get("used", 0) or 0)
        if date != today_pacific_iso():
            return today_pacific_iso(), 0
        return date, used

    def set_budget(self, date: str, used: int) -> None:
        meta = self._read_meta()
        meta["budget_date"] = date
        meta["used"] = int(used)
        self._write_meta(meta)

    def acquire_run_lock(self, ttl_seconds: int) -> bool:
        meta = self._read_meta()
        now = time.time()
        running_since = meta.get("running_since")
        if meta.get("running") and running_since and (now - float(running_since)) < ttl_seconds:
            return False
        meta["running"] = True
        meta["running_since"] = now
        self._write_meta(meta)
        return True

    def release_run_lock(self) -> None:
        meta = self._read_meta()
        meta["running"] = False
        meta["running_since"] = None
        self._write_meta(meta)

    # -- scenario state ----------------------------------------------------

    def _scenario_path(self, scenario_id: str) -> Path:
        return self.root / "scenarios" / f"{scenario_id}.json"

    def get_scenario_state(self, scenario_id: str) -> ScenarioStateRow | None:
        p = self._scenario_path(scenario_id)
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return ScenarioStateRow(
            scenario_id=d["scenario_id"],
            running_summary=d.get("running_summary", ""),
            turn_count=int(d.get("turn_count", 0)),
            formative_memories=d.get("formative_memories", {}),
            initialized=bool(d.get("initialized", False)),
            updated_ts=d.get("updated_ts", now_utc_iso()),
        )

    def upsert_scenario_state(self, row: ScenarioStateRow) -> None:
        row.updated_ts = now_utc_iso()
        self._scenario_path(row.scenario_id).write_text(
            json.dumps(asdict(row)), encoding="utf-8"
        )

    # -- entity state ------------------------------------------------------

    def _read_entities(self) -> dict[str, dict[str, dict]]:
        try:
            return json.loads(self._entity_path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def _write_entities(self, data: dict) -> None:
        tmp = self._entity_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, self._entity_path)

    def get_entity_states(self, scenario_id: str) -> list[EntityStateRow]:
        data = self._read_entities()
        rows = data.get(scenario_id, {})
        return [EntityStateRow(**_coerce_row(r)) for r in rows.values()]

    def upsert_entity_state(self, row: EntityStateRow) -> None:
        data = self._read_entities()
        data.setdefault(row.scenario_id, {})[row.entity_id] = asdict(row)
        self._write_entities(data)

    # -- turn log ----------------------------------------------------------

    def append_turn_log(self, row: TurnLogRow) -> None:
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row.to_dict()) + "\n")

    def get_recent_turns(self, scenario_id: str, limit: int) -> list[TurnLogRow]:
        if not self._log_path.exists():
            return []
        rows: list[TurnLogRow] = []
        # Read whole file (small in practice; the durable log can be trimmed).
        with self._log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("scenario_id") == scenario_id:
                    rows.append(_turn_row_from_dict(d))
        return rows[-limit:]


def _coerce_row(r: dict) -> dict:
    """Ensure an entity-state dict has all expected keys."""
    return {
        "scenario_id": r["scenario_id"],
        "entity_id": r["entity_id"],
        "mood": r.get("mood", ""),
        "stress": r.get("stress", "medium"),
        "stances": r.get("stances", {}),
        "last_utterance": r.get("last_utterance", ""),
        "last_turn_ts": r.get("last_turn_ts", now_utc_iso()),
    }


def _turn_row_from_dict(d: dict) -> TurnLogRow:
    return TurnLogRow(
        scenario_id=d["scenario_id"],
        entity_id=d["entity_id"],
        utterance=d.get("utterance", ""),
        trigger=d.get("trigger", {}),
        state_change=d.get("state_change", {}),
        emotion_snapshot=d.get("emotion_snapshot", {}),
        model=d.get("model", ""),
        raw_meta=d.get("raw_meta", {}),
        turn_index=int(d.get("turn_index", 0)),
        ts=d.get("ts", now_utc_iso()),
        turn_id=d.get("turn_id", str(uuid.uuid4())),
    )


# ---------------------------------------------------------------------------
# Supabase backend
# ---------------------------------------------------------------------------


class SupabaseStore:
    """Supabase (Free Postgres) backend using the service_role key for writes.

    The frontend reads the same tables with the anon key under RLS (SELECT-only).
    Requires the schema in ``supabase/schema.sql`` to be applied first.
    """

    def __init__(self, url: str, service_key: str) -> None:
        from supabase import create_client
        self._client = create_client(url, service_key)

    # -- budget / lock -----------------------------------------------------

    def _meta_rpc_or_table(self):
        return self._client.table("sim_meta")

    def get_budget(self) -> tuple[str, int]:
        today = today_pacific_iso()
        res = self._meta_rpc_or_table().select("*").eq("id", "budget").execute()
        if not res.data:
            return today, 0
        row = res.data[0]
        if row.get("budget_date") != today:
            return today, 0
        return today, int(row.get("used", 0))

    def set_budget(self, date: str, used: int) -> None:
        self._meta_rpc_or_table().upsert(
            {"id": "budget", "budget_date": date, "used": int(used)}
        ).execute()

    def acquire_run_lock(self, ttl_seconds: int) -> bool:
        # Read existing lock row.
        res = (
            self._meta_rpc_or_table()
            .select("*")
            .eq("id", "run_lock")
            .execute()
        )
        now = time.time()
        if res.data:
            row = res.data[0]
            if row.get("running") and row.get("running_since"):
                age = now - float(row["running_since"])
                if age < ttl_seconds:
                    return False
        self._meta_rpc_or_table().upsert(
            {"id": "run_lock", "running": True, "running_since": now}
        ).execute()
        return True

    def release_run_lock(self) -> None:
        self._meta_rpc_or_table().upsert(
            {"id": "run_lock", "running": False, "running_since": None}
        ).execute()

    # -- scenario state ----------------------------------------------------

    def get_scenario_state(self, scenario_id: str) -> ScenarioStateRow | None:
        res = (
            self._client.table("sim_scenario")
            .select("*")
            .eq("scenario_id", scenario_id)
            .execute()
        )
        if not res.data:
            return None
        d = res.data[0]
        return ScenarioStateRow(
            scenario_id=d["scenario_id"],
            running_summary=d.get("running_summary", ""),
            turn_count=int(d.get("turn_count", 0)),
            formative_memories=d.get("formative_memories", {}) or {},
            initialized=bool(d.get("initialized", False)),
            updated_ts=d.get("updated_ts", now_utc_iso()),
        )

    def upsert_scenario_state(self, row: ScenarioStateRow) -> None:
        row.updated_ts = now_utc_iso()
        self._client.table("sim_scenario").upsert(
            {
                "scenario_id": row.scenario_id,
                "running_summary": row.running_summary,
                "turn_count": row.turn_count,
                "formative_memories": row.formative_memories,
                "initialized": row.initialized,
                "updated_ts": row.updated_ts,
            }
        ).execute()

    # -- entity state ------------------------------------------------------

    def get_entity_states(self, scenario_id: str) -> list[EntityStateRow]:
        res = (
            self._client.table("entity_state")
            .select("*")
            .eq("scenario_id", scenario_id)
            .execute()
        )
        return [EntityStateRow(**_coerce_row(r)) for r in (res.data or [])]

    def upsert_entity_state(self, row: EntityStateRow) -> None:
        self._client.table("entity_state").upsert(
            {
                "scenario_id": row.scenario_id,
                "entity_id": row.entity_id,
                "mood": row.mood,
                "stress": row.stress,
                "stances": row.stances,
                "last_utterance": row.last_utterance,
                "last_turn_ts": row.last_turn_ts,
            }
        ).execute()

    # -- turn log ----------------------------------------------------------

    def append_turn_log(self, row: TurnLogRow) -> None:
        d = row.to_dict()
        self._client.table("sim_turn_log").insert(
            {
                "turn_id": d["turn_id"],
                "turn_index": d["turn_index"],
                "ts": d["ts"],
                "scenario_id": d["scenario_id"],
                "entity_id": d["entity_id"],
                "utterance": d["utterance"],
                "trigger": d["trigger"],
                "state_change": d["state_change"],
                "emotion_snapshot": d["emotion_snapshot"],
                "model": d["model"],
                "raw_meta": d["raw_meta"],
            }
        ).execute()

    def get_recent_turns(self, scenario_id: str, limit: int) -> list[TurnLogRow]:
        res = (
            self._client.table("sim_turn_log")
            .select("*")
            .eq("scenario_id", scenario_id)
            .order("turn_index", desc=True)
            .limit(limit)
            .execute()
        )
        rows = [_turn_row_from_dict(d) for d in (res.data or [])]
        rows.reverse()  # oldest -> newest
        return rows


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_store(config) -> StateStore:
    """Pick the backend: Supabase when configured, else local JSON files."""
    if config.use_supabase:
        return SupabaseStore(config.supabase_url, config.supabase_service_key)
    return LocalJSONStore(config.local_state_dir)
