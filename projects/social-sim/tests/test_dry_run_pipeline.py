"""End-to-end dry-run test: one scenario advances and persists correctly.

Uses the stub LLM + local JSON store (no Gemini key, no Supabase, no network).
This is the test the tester agent relies on.
"""

from pathlib import Path

from sim.config import Config
from sim.gemini_client import BudgetCounter, build_model, make_embedder
from sim.personas import load_personas
from sim.pipeline import advance_entity_turn, run_tick
from sim import state_store as ss


PERSONAS = Path(__file__).resolve().parent.parent / "personas.md"


def _make_store(tmp_path) -> ss.LocalJSONStore:
    return ss.LocalJSONStore(tmp_path / "state")


def _config(tmp_path) -> Config:
    base = Config.from_env(force_dry_run=True)
    return Config(
        **{**base.__dict__, "local_state_dir": str(tmp_path / "state")}
    )


def test_advance_one_turn_produces_valid_rows(tmp_path):
    store = _make_store(tmp_path)
    cfg = _config(tmp_path)
    model = build_model(cfg, BudgetCounter(cfg.daily_request_budget))
    embedder = make_embedder(cfg)
    scenarios = load_personas(PERSONAS)
    family = next(s for s in scenarios if s.id == "family")

    result = advance_entity_turn(store, family, "Renata", model, embedder, cfg.memory_window_turns)

    assert result is not None
    assert result.entity_id == "Renata"
    assert result.utterance  # non-empty
    assert result.model_calls_made > 0

    # entity_state upsert shape. Cold start seeds ALL 4 entities in the scenario
    # so the dashboard shows every persona from the first cycle.
    rows = store.get_entity_states("family")
    assert len(rows) == 4
    row = next(r for r in rows if r.entity_id == "Renata")
    assert row.entity_id == "Renata"
    assert row.mood
    assert row.stress in {"low", "medium", "high"}
    assert set(row.stances.keys()) == {"Tobias", "Mira", "Leo"}
    assert row.last_utterance
    assert row.last_turn_ts

    # sim_turn_log row shape (append-only research log)
    turns = store.get_recent_turns("family", 5)
    assert len(turns) == 1
    t = turns[0]
    assert t.scenario_id == "family"
    assert t.entity_id == "Renata"
    assert t.utterance
    assert t.turn_id  # uuid
    assert t.ts
    assert t.model
    assert isinstance(t.trigger, dict) and "type" in t.trigger
    assert isinstance(t.state_change, dict)
    assert isinstance(t.emotion_snapshot, dict)
    assert {"mood", "stress", "stances"} <= set(t.emotion_snapshot.keys())
    assert isinstance(t.raw_meta, dict) and "resolved_event" in t.raw_meta


def test_cold_start_seeds_all_entities(tmp_path):
    store = _make_store(tmp_path)
    cfg = _config(tmp_path)
    model = build_model(cfg, BudgetCounter(cfg.daily_request_budget))
    embedder = make_embedder(cfg)
    scenarios = load_personas(PERSONAS)
    family = next(s for s in scenarios if s.id == "family")

    advance_entity_turn(store, family, "Renata", model, embedder, cfg.memory_window_turns)

    # Cold start must seed dashboard rows for ALL 4 entities in the scenario.
    rows = store.get_entity_states("family")
    assert {r.entity_id for r in rows} == {"Renata", "Tobias", "Mira", "Leo"}
    for r in rows:
        assert r.mood and r.stress in {"low", "medium", "high"}


def test_run_tick_full_cycle_offline(tmp_path):
    store = _make_store(tmp_path)
    cfg = _config(tmp_path)
    model = build_model(cfg, BudgetCounter(cfg.daily_request_budget))
    embedder = make_embedder(cfg)
    scenarios = load_personas(PERSONAS)

    summary = run_tick(cfg, store, model, embedder, scenarios)
    assert summary["status"] == "ok"
    assert summary["dry_run"] is True
    # First tick = cold start for all 16 entities.
    assert summary["advanced"] == 16

    # 16 log rows total across 4 scenarios.
    log_path = Path(tmp_path) / "state" / "sim_turn_log.jsonl"
    all_rows = [l for l in log_path.read_text().splitlines() if l.strip()]
    assert len(all_rows) == 16

    # An immediate second tick advances nothing (60-min interval not elapsed).
    summary2 = run_tick(cfg, store, model, embedder, scenarios)
    assert summary2["advanced"] == 0


def test_budget_exhaustion_persists_and_next_tick_noops(tmp_path):
    """Regression: when a turn exhausts the HARD daily budget mid-run, the day
    must be marked exhausted so the next cron tick no-ops instead of retrying a
    spent quota (the silent "1 turn ever" bug).

    With a budget of 1 the stub exhausts during the first turn; the pipeline
    must persist exhaustion, and the very next tick must advance NOTHING.
    """
    store = _make_store(tmp_path)
    base = _config(tmp_path)
    cfg = Config(**{**base.__dict__, "daily_request_budget": 1})
    model = build_model(cfg, BudgetCounter(cfg.daily_request_budget))
    embedder = make_embedder(cfg)
    scenarios = load_personas(PERSONAS)

    run_tick(cfg, store, model, embedder, scenarios)

    # The day must now be persisted as exhausted.
    _, used = store.get_budget()
    assert used >= cfg.daily_request_budget

    # The next tick must not attempt any model work (budget_remaining == 0).
    summary2 = run_tick(cfg, store, model, embedder, scenarios)
    assert summary2["status"] == "ok"
    assert summary2["advanced"] == 0
