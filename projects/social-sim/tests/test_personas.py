"""Tests: persona parsing (the source of truth)."""

from pathlib import Path

import pytest

from sim.personas import (
    BIG_FIVE_FACETS,
    all_entities,
    load_personas,
    normalize_stress,
)

PERSONAS_PATH = Path(__file__).resolve().parent.parent / "personas.md"


@pytest.fixture(scope="module")
def scenarios():
    return load_personas(PERSONAS_PATH)


def test_four_scenarios(scenarios):
    assert len(scenarios) == 4
    assert {s.id for s in scenarios} == {"family", "corporation", "university", "ward"}


def test_sixteen_entities(scenarios):
    ents = all_entities(scenarios)
    assert len(ents) == 16
    # Names are unique and clean (no Markdown artifacts).
    names = [e.name for e in ents]
    assert len(set(names)) == 16
    assert all("#" not in n and "*" not in n for n in names)
    # Spot-check a few known personas.
    assert "Renata" in names
    assert "Theo" in names
    assert "Jamal" in names
    assert "Wren" in names


def test_each_entity_has_all_five_facets(scenarios):
    ents = all_entities(scenarios)
    assert ents
    for e in ents:
        missing = [f for f in BIG_FIVE_FACETS if f not in e.big_five]
        assert not missing, f"{e.name} missing facets {missing}; got {e.big_five}"
        for f in BIG_FIVE_FACETS:
            assert e.big_five[f], f"{e.name}.{f} is empty"


def test_each_entity_has_emotional_state(scenarios):
    for e in all_entities(scenarios):
        assert e.mood, f"{e.name} has no mood"
        assert e.stress in {"low", "medium", "high"}, f"{e.name} bad stress {e.stress}"
        assert len(e.stances) >= 3, f"{e.name} has {len(e.stances)} stances"
        assert len(e.initial_relationships) >= 3, (
            f"{e.name} has {len(e.initial_relationships)} relationships"
        )


def test_ward_has_ethics_notice(scenarios):
    ward = next(s for s in scenarios if s.id == "ward")
    assert ward.ethics_notice
    assert "fiction" in ward.ethics_notice.lower() or "therapeutic" in ward.ethics_notice.lower()


def test_shared_problems_present(scenarios):
    for s in scenarios:
        assert s.shared_problem, f"{s.id} has no shared problem"
        assert s.environment, f"{s.id} has no environment"


def test_normalize_stress():
    assert normalize_stress("medium-high") == "high"
    assert normalize_stress("low-medium") == "low"
    assert normalize_stress("high") == "high"
    assert normalize_stress("Low-Medium") == "low"


def test_persona_context_is_usable(scenarios):
    e = all_entities(scenarios)[0]
    ctx = e.persona_context
    assert "Name:" in ctx and "Role:" in ctx
    assert "Openness:" in ctx  # Big Five rendered
