"""Scheduler: decide which scenario(s)/entities are DUE each cron run.

Constraints enforced (per the project brief):
* **60-minute staggered turn cadence** across the 4 scenarios. Each entity speaks
  ~once per 60-minute cycle; the 4 scenarios are given per-scenario stagger
  offsets so they don't all fire at the same cron tick.
* **HARD daily budget** (``DAILY_REQUEST_BUDGET``): once exhausted, no more
  Gemini calls this (Pacific) day. RPD is the binding constraint.
* **Per-run cap** (``MAX_CALLS_PER_RUN``) and a remaining-budget ceiling.
* **Per-entity interval**: an entity is due when ``now - last_turn_ts >= interval``.

The scheduler is pure-ish: given the current time, the persisted last-turn
timestamps, the budget, and the config, it returns an ordered list of
``AdvanceItem``(s) to run this tick. The pipeline actually executes them and
spends the budget.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass
class AdvanceItem:
    """A single entity turn to advance this run."""

    scenario_id: str
    entity_id: str
    reason: str = ""


@dataclass
class SchedulerConfig:
    daily_request_budget: int
    turn_interval_seconds: int
    max_calls_per_run: int
    # Per-scenario stagger offset in seconds within the 60-min cycle, so the four
    # scenarios fire at different ticks rather than simultaneously.
    stagger_offsets: dict[str, float]

    @classmethod
    def from_config(cls, cfg) -> "SchedulerConfig":
        ids = ["family", "corporation", "university", "ward"]
        # Spread the 4 scenarios evenly across the cycle.
        cycle = max(1, cfg.turn_interval_seconds)
        step = cycle / max(1, len(ids))
        return cls(
            daily_request_budget=cfg.daily_request_budget,
            turn_interval_seconds=cfg.turn_interval_seconds,
            max_calls_per_run=cfg.max_calls_per_run,
            stagger_offsets={sid: round(i * step, 1) for i, sid in enumerate(ids)},
        )


def _parse_ts(ts: str | None) -> float | None:
    """Parse an ISO timestamp to epoch seconds, tolerant of variants."""
    if not ts:
        return None
    from datetime import datetime
    for fmt in (None,):  # try fromisoformat first
        try:
            s = ts.replace("Z", "+00:00")
            return datetime.fromisoformat(s).timestamp()
        except (ValueError, TypeError):
            break
    try:
        return float(ts)
    except (TypeError, ValueError):
        return None


def select_due(
    sched_cfg: SchedulerConfig,
    *,
    now_ts: float,
    scenario_ids: list[str],
    entity_ids_by_scenario: dict[str, list[str]],
    last_turn_ts: Mapping[tuple[str, str], str | None],
    budget_remaining: int,
) -> list[AdvanceItem]:
    """Return the ordered list of entity turns that are due this run.

    Args:
        sched_cfg: scheduler parameters.
        now_ts: current epoch seconds.
        scenario_ids: ordered scenario ids.
        entity_ids_by_scenario: entity ids per scenario (turn order within a scenario).
        last_turn_ts: {(scenario_id, entity_id): iso_ts_or_None}.
        budget_remaining: requests left in the daily budget.

    The result is capped by ``max_calls_per_run`` and ``budget_remaining``.
    """
    if budget_remaining <= 0:
        return []

    due: list[AdvanceItem] = []

    for sid in scenario_ids:
        offset = sched_cfg.stagger_offsets.get(sid, 0.0)
        adjusted_now = now_ts - offset
        for eid in entity_ids_by_scenario.get(sid, []):
            last = _parse_ts(last_turn_ts.get((sid, eid)))
            if last is None:
                # Never spoken -> due immediately (cold start).
                due.append(
                    AdvanceItem(sid, eid, reason="cold-start")
                )
            elif (adjusted_now - last) >= sched_cfg.turn_interval_seconds:
                due.append(
                    AdvanceItem(sid, eid, reason="interval-elapsed")
                )

    # Cap by per-run limit and remaining budget.
    cap = min(sched_cfg.max_calls_per_run, budget_remaining)
    return due[:cap]


def is_budget_exhausted(used: int, daily_budget: int) -> bool:
    """True when the daily budget is spent."""
    return used >= daily_budget


def estimate_daily_turns_per_entity(
    daily_budget: int, calls_per_turn: int, num_entities: int = 16
) -> float:
    """Rough expected turns/entity/day given the budget and per-turn call cost.

    The 60-min cadence is the *target*; the budget is HARD. If the per-turn call
    cost makes 24 turns/entity/day infeasible, the scheduler simply advances fewer
    turns and entities wait. This helper documents that tension.
    """
    if calls_per_turn <= 0 or num_entities <= 0:
        return 0.0
    return (daily_budget / calls_per_turn) / num_entities


def sleep_for_spacing(seconds: float) -> None:
    """Thin wrapper used by the pipeline to respect RPM between turns."""
    if seconds > 0:
        time.sleep(seconds)
