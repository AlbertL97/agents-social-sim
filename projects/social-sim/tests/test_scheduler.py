"""Tests: scheduler due/budget math and staggering."""

from sim.scheduler import (
    AdvanceItem,
    SchedulerConfig,
    estimate_daily_turns_per_entity,
    is_budget_exhausted,
    select_due,
)


def _cfg(budget=1000, interval=3600, max_per_run=40):
    return SchedulerConfig(
        daily_request_budget=budget,
        turn_interval_seconds=interval,
        max_calls_per_run=max_per_run,
        stagger_offsets={"family": 0, "corporation": 900, "university": 1800, "ward": 2700},
    )


SCENARIO_IDS = ["family", "corporation", "university", "ward"]
ENTITIES = {sid: ["A", "B", "C", "D"] for sid in SCENARIO_IDS}


def test_cold_start_all_due():
    """Never-spoken entities are all due immediately."""
    due = select_due(
        _cfg(),
        now_ts=1_000_000,
        scenario_ids=SCENARIO_IDS,
        entity_ids_by_scenario=ENTITIES,
        last_turn_ts={(s, e): None for s in SCENARIO_IDS for e in ENTITIES[s]},
        budget_remaining=1000,
    )
    assert len(due) == 16
    assert all(item.reason == "cold-start" for item in due)


def test_budget_exhaustion_stops_calls():
    """Zero remaining budget -> nothing is due, even on cold start."""
    due = select_due(
        _cfg(),
        now_ts=1_000_000,
        scenario_ids=SCENARIO_IDS,
        entity_ids_by_scenario=ENTITIES,
        last_turn_ts={(s, e): None for s in SCENARIO_IDS for e in ENTITIES[s]},
        budget_remaining=0,
    )
    assert due == []
    assert is_budget_exhausted(1000, 1000)
    assert not is_budget_exhausted(999, 1000)


def test_interval_not_elapsed_blocks_advance():
    """All entities spoke recently -> none due within the interval."""
    now = 1_000_000
    last = {  # all spoke 5 minutes ago (well under 60)
        (s, e): "1970-01-01T00:00:00+00:00" for s in SCENARIO_IDS for e in ENTITIES[s]
    }
    # Use a recent ISO timestamp by computing from now.
    from datetime import datetime, timezone, timedelta
    recent = (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=now - 300)).isoformat()
    last = {(s, e): recent for s in SCENARIO_IDS for e in ENTITIES[s]}
    due = select_due(
        _cfg(),
        now_ts=now,
        scenario_ids=SCENARIO_IDS,
        entity_ids_by_scenario=ENTITIES,
        last_turn_ts=last,
        budget_remaining=1000,
    )
    assert due == []


def test_staggering_spreads_scenarios():
    """At +66min, only the zero-offset scenario (family) becomes due first."""
    from datetime import datetime, timezone, timedelta
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    now_ts = (base + timedelta(minutes=66)).timestamp()
    last = {(s, e): base.isoformat() for s in SCENARIO_IDS for e in ENTITIES[s]}
    due = select_due(
        _cfg(),
        now_ts=now_ts,
        scenario_ids=SCENARIO_IDS,
        entity_ids_by_scenario=ENTITIES,
        last_turn_ts=last,
        budget_remaining=1000,
    )
    scenarios_due = {item.scenario_id for item in due}
    # family (offset 0) elapsed = 66min >= 60 -> due. corporation (offset 15min)
    # adjusted elapsed = 66-15 = 51min < 60 -> not due. So only family is due.
    assert scenarios_due == {"family"}


def test_max_per_run_cap():
    """Per-run cap limits how many turns advance in one tick."""
    due = select_due(
        _cfg(max_per_run=3),
        now_ts=1_000_000,
        scenario_ids=SCENARIO_IDS,
        entity_ids_by_scenario=ENTITIES,
        last_turn_ts={(s, e): None for s in SCENARIO_IDS for e in ENTITIES[s]},
        budget_remaining=1000,
    )
    assert len(due) == 3


def test_estimate_documents_budget_tension():
    """1000 budget, ~5 calls/turn, 16 entities => well under 24 turns/entity/day."""
    turns = estimate_daily_turns_per_entity(1000, calls_per_turn=5, num_entities=16)
    assert 0 < turns < 24
