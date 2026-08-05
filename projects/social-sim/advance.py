#!/usr/bin/env python3
"""Cron entry point for the social-sim (stateless batch advance).

GitHub Actions fires this every ~10 minutes (``.github/workflows/social-sim.yml``).
Each run loads persisted state, advances whichever scenario/entity turns are DUE
per the 60-min staggered cadence (respecting the HARD daily budget), persists the
results, and exits. There is NO always-on server.

Usage:
    python advance.py            # auto dry-run if GEMINI_API_KEY unset
    python advance.py --dry-run  # force the offline stub LLM + local JSON store
    python advance.py --once <scenario_id> <entity_id>   # advance one specific turn

Local dry-run (no key, no Supabase) writes to ``.local-state/``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure the sim package is importable when run from the project dir.
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from sim.config import Config  # noqa: E402
from sim.gemini_client import BudgetCounter, build_model, make_embedder  # noqa: E402
from sim.personas import load_personas  # noqa: E402
from sim.pipeline import run_tick, advance_entity_turn  # noqa: E402
from sim import state_store as ss  # noqa: E402


def _load_env_file(path: str) -> None:
    """Minimal .env loader (only sets vars not already in the environment)."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if key and key not in os.environ:
            os.environ[key] = val


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Advance the social simulation one tick.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Force the offline stub LLM + local JSON store."
    )
    parser.add_argument(
        "--personas",
        default=str(_THIS_DIR / "personas.md"),
        help="Path to personas.md (default: alongside this file).",
    )
    parser.add_argument(
        "--once", nargs=2, metavar=("SCENARIO_ID", "ENTITY_ID"),
        help="Advance exactly one turn for the given scenario/entity (ignores scheduler).",
    )
    args = parser.parse_args(argv)

    # Load .env if present (local dev). Production uses GitHub Actions secrets.
    _load_env_file(str(_THIS_DIR / ".env"))

    config = Config.from_env(force_dry_run=args.dry_run)
    if config.dry_run:
        print("[advance] DRY-RUN: using stub LLM + local JSON backend (no key, no network).")
    else:
        print(f"[advance] LIVE: model={config.gemini_model} budget={config.daily_request_budget}/day")

    scenarios = load_personas(args.personas)
    store = ss.build_store(config)
    model = build_model(config, BudgetCounter(config.daily_request_budget))
    embedder = make_embedder(config)

    if args.once:
        sid, eid = args.once
        scenario = next((s for s in scenarios if s.id == sid), None)
        if scenario is None:
            print(f"[advance] unknown scenario id: {sid}")
            return 2
        result = advance_entity_turn(
            store, scenario, eid, model, embedder, config.memory_window_turns
        )
        if result is None:
            print("[advance] no turn advanced (budget exhausted?).")
            return 3
        print(json.dumps(
            {"scenario_id": sid, "entity_id": eid, "utterance": result.utterance},
            indent=2,
        ))
        return 0

    summary = run_tick(config, store, model, embedder, scenarios)
    print("[advance] tick summary:")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
