"""Orchestrate a single ephemeral cron tick: load -> schedule -> advance -> persist.

This wires together the scheduler, the stateless Concordia engine, and the
persistence layer. ``advance.py`` calls ``run_tick`` once per GitHub Actions run.
Each run advances whichever entity turns are DUE (60-min staggered cadence),
respecting the HARD daily budget and per-run cap, then exits. No always-on server.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from .concordia_engine import (  # noqa: TID252 - intra-package import
    ScenarioEngine,
    TurnResult,
    persona_formative_memories,
    enrich_formative_via_initializer,
)
from .gemini_client import BudgetCounter, BudgetExhausted
from .scheduler import SchedulerConfig, select_due
from .personas import ScenarioDef
from . import state_store as ss


RUN_LOCK_TTL_SECONDS = 600  # 10 min: a run should finish well within one cron tick.
SUMMARY_MAX_EVENTS = 15      # cap the running summary length (no extra LLM call).


def _utc_now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _last_turn_index(scenario_state) -> int:
    return scenario_state.turn_count if scenario_state else 0


def cold_start_scenario(
    store: ss.StateStore,
    scenario: ScenarioDef,
    model,
    embedder,
    enrich: bool,
) -> ss.ScenarioStateRow:
    """Initialize a scenario: seed formative memories + all entity_state rows."""
    deterministic = {e.name: persona_formative_memories(e) for e in scenario.entities}
    if enrich:
        # Production-only: enrich with LLM backstory via the Concordia initializer.
        formative = enrich_formative_via_initializer(
            scenario, model, embedder, deterministic
        )
    else:
        formative = deterministic

    # Seed every entity's dashboard row with its starting snapshot.
    for e in scenario.entities:
        store.upsert_entity_state(
            ss.EntityStateRow(
                scenario_id=scenario.id,
                entity_id=e.name,
                mood=e.mood or "engaged",
                stress=e.stress,
                stances=dict(e.stances),
                last_utterance="",
                last_turn_ts=None,
            )
        )

    row = ss.ScenarioStateRow(
        scenario_id=scenario.id,
        running_summary="",
        turn_count=0,
        formative_memories=formative,
        initialized=True,
    )
    store.upsert_scenario_state(row)
    return row


def advance_entity_turn(
    store: ss.StateStore,
    scenario: ScenarioDef,
    entity_id: str,
    model,
    embedder,
    memory_window_turns: int,
) -> TurnResult | None:
    """Reconstruct + advance one entity turn, then persist all outputs."""
    scenario_state = store.get_scenario_state(scenario.id)
    if scenario_state is None or not scenario_state.initialized:
        scenario_state = cold_start_scenario(
            store, scenario, model, embedder, enrich=False
        )

    recent = store.get_recent_turns(scenario.id, memory_window_turns)
    engine = ScenarioEngine(scenario, model, embedder, memory_window_turns)
    entities = engine.build_entities(
        formative_memories=scenario_state.formative_memories,
        recent_turns=[_turn_to_dict(t) for t in recent],
        running_summary=scenario_state.running_summary,
    )

    try:
        result = engine.advance_turn(entity_id, entities, recent)
    except BudgetExhausted:
        return None

    # Persist the append-only research log row.
    snap = result.resolution.get("emotion_snapshot", {})
    store.append_turn_log(
        ss.TurnLogRow(
            scenario_id=scenario.id,
            entity_id=entity_id,
            utterance=result.utterance,
            trigger=result.resolution.get("trigger", {}),
            state_change=result.resolution.get("state_change", {}),
            emotion_snapshot=snap,
            model=_model_name(model),
            raw_meta={"resolved_event": result.resolution.get("resolved_event", "")},
            turn_index=scenario_state.turn_count + 1,
        )
    )

    # Upsert the speaker's fast-dashboard row.
    others = [e.name for e in scenario.entities if e.name != entity_id]
    stances = {o: snap.get("stances", {}).get(o, "") for o in others}
    store.upsert_entity_state(
        ss.EntityStateRow(
            scenario_id=scenario.id,
            entity_id=entity_id,
            mood=snap.get("mood", ""),
            stress=snap.get("stress", "medium"),
            stances=stances,
            last_utterance=result.utterance,
            last_turn_ts=ss.now_utc_iso(),
        )
    )

    # Update the scenario reconstruction context (running summary + turn count).
    resolved = result.resolution.get("resolved_event", result.utterance)
    events = _parse_summary(scenario_state.running_summary)
    events.append(f"[{entity_id}] {resolved}")
    new_summary = " | ".join(events[-SUMMARY_MAX_EVENTS:])
    scenario_state.running_summary = new_summary
    scenario_state.turn_count = scenario_state.turn_count + 1
    store.upsert_scenario_state(scenario_state)

    return result


def _turn_to_dict(turn) -> dict:
    if isinstance(turn, dict):
        return turn
    return {
        "entity_id": turn.entity_id,
        "utterance": turn.utterance,
        "ts": turn.ts,
    }


def _parse_summary(summary: str) -> list[str]:
    if not summary:
        return []
    return [p.strip() for p in summary.split(" | ") if p.strip()]


def _model_name(model) -> str:
    return getattr(model, "__class__", type(model)).__name__


def run_tick(
    config,
    store: ss.StateStore,
    model,
    embedder,
    scenarios: list[ScenarioDef],
    *,
    now_ts: float | None = None,
    max_turns_override: int | None = None,
) -> dict[str, Any]:
    """Execute one cron tick. Returns a summary dict for logging."""
    now_ts = now_ts if now_ts is not None else _utc_now_ts()

    if not store.acquire_run_lock(RUN_LOCK_TTL_SECONDS):
        return {"status": "skipped_overlap", "advanced": 0, "reason": "run lock held"}

    advanced: list[dict[str, Any]] = []
    error: str | None = None
    budget_used = 0
    budget_limit = config.daily_request_budget
    dry_run = config.dry_run
    try:
        # Budget (resets at midnight Pacific).
        bdate, used = store.get_budget()
        budget = BudgetCounter(config.daily_request_budget, used=used)
        budget_limit = budget.daily_limit

        sched_cfg = SchedulerConfig.from_config(config)
        scenario_ids = [s.id for s in scenarios]
        entity_ids_by_scenario = {
            s.id: [e.name for e in s.entities] for s in scenarios
        }

        # Gather last-turn timestamps from persisted entity_state rows.
        last_turn_ts: dict[tuple[str, str], str | None] = {}
        for sid in scenario_ids:
            rows = store.get_entity_states(sid)
            by_entity = {r.entity_id: r for r in rows}
            for s in scenarios:
                if s.id != sid:
                    continue
                for e in s.entities:
                    row = by_entity.get(e.name)
                    last_turn_ts[(sid, e.name)] = row.last_turn_ts if row else None

        due = select_due(
            sched_cfg,
            now_ts=now_ts,
            scenario_ids=scenario_ids,
            entity_ids_by_scenario=entity_ids_by_scenario,
            last_turn_ts=last_turn_ts,
            budget_remaining=budget.remaining(),
        )
        if max_turns_override is not None:
            due = due[:max_turns_override]

        for item in due:
            scenario = next(s for s in scenarios if s.id == item.scenario_id)
            try:
                result = advance_entity_turn(
                    store, scenario, item.entity_id, model, embedder,
                    config.memory_window_turns,
                )
            except BudgetExhausted:
                break
            except Exception as exc:
                error = f"{item.scenario_id}/{item.entity_id}: {exc!r}"
                break
            if result is None:
                break
            # Re-read budget so the HARD cap is respected across turns within a run.
            _, used = store.get_budget()
            used += result.model_calls_made
            store.set_budget(bdate, used)
            budget.used = used
            advanced.append(
                {
                    "scenario_id": item.scenario_id,
                    "entity_id": item.entity_id,
                    "utterance": result.utterance[:120],
                    "calls": result.model_calls_made,
                }
            )
            if budget.remaining() <= 0:
                break
        budget_used = budget.used
    except Exception as exc:
        error = f"tick aborted: {exc!r}"
    finally:
        store.release_run_lock()

    return {
        "status": "ok" if error is None else "error",
        "error": error,
        "advanced": len(advanced),
        "items": advanced,
        "budget_used": budget_used,
        "budget_limit": budget_limit,
        "dry_run": dry_run,
    }
