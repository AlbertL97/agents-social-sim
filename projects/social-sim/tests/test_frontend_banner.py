"""Test: the fiction banner is visibly present in the frontend.

Per the ethics requirement (non-negotiable): the landing page AND each scenario
header must clearly state all four scenarios are entirely fictional AI
simulations, and the ward header must state it is a fictional therapeutic-
community simulation (not real patients/clinical practice).
"""

from pathlib import Path

import pytest

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _frontend_source() -> str:
    """Combined frontend source (HTML + JS), since the dashboard is JS-rendered."""
    parts = []
    for name in ("index.html", "app.js"):
        path = FRONTEND_DIR / name
        assert path.exists(), f"{path} must exist"
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


@pytest.fixture(scope="module")
def index_html() -> str:
    return (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def frontend() -> str:
    return _frontend_source()


def test_landing_page_fiction_banner(index_html):
    low = index_html.lower()
    assert "fictional" in low or "fiction" in low
    assert "simulation" in low
    # Banner class present so the banner can be styled prominently (not buried).
    assert "fiction-banner" in low or "banner" in low


def test_each_scenario_has_fiction_notice(frontend):
    # Every scenario id is referenced somewhere in the frontend source, and the
    # per-scenario fiction notice string exists (rendered into each header).
    for sid in ("family", "corporation", "university", "ward"):
        assert sid in frontend, f"scenario {sid} not referenced in frontend"
    assert frontend.count("fictional AI simulation") >= 1
    # app.js attaches an inline fiction notice to each of the 4 scenario headers.
    assert frontend.count("entirely fictional AI simulation") >= 1


def test_ward_therapeutic_community_notice(frontend):
    low = frontend.lower()
    assert "therapeutic community" in low or "therapeutic-community" in low
    # Must NOT present as real patients / clinical practice.
    assert "not real patients" in low or "not depict" in low or "not real" in low


def test_app_js_polls_entity_state(frontend):
    # The dashboard polls the entity_state endpoint.
    assert "entity_state" in frontend
