# agents-workflow

A mono-repo for multi-agent workflow experiments. The headline project is
**social-sim** — a live, always-on multi-agent social simulation dashboard.

## Projects

| Path | What it is |
|------|------------|
| [`projects/social-sim/`](projects/social-sim/) | Live multi-agent social simulation dashboard (Concordia + Gemini + Supabase). |
| [`projects/word_frequency/`](projects/word_frequency/) | Small word-frequency utility + unit tests. |

---

## social-sim — architecture in one diagram

```
            every ~10 min
  GitHub Actions (cron) ──► advance.py  (ephemeral, single tick)
                                │
                                ▼
                         sim/pipeline.py
                                │
        ┌───────────────────────┼────────────────────────────┐
        ▼                       ▼                            ▼
  sim/scheduler.py       sim/concordia_engine.py      sim/gemini_client.py
  due/budget math        stateless entity +           Gemini dialogue +
  (HARD daily cap,       lean turn advance            embeddings  (HARD budget,
   60-min stagger)       (re-seeded from transcript)   backoff + jitter)
        │                       │                            │
        └───────────► sim/state_store.py ◄────────────────────┘
                          persist (upsert + append)
                                │
                ┌───────────────┴───────────────┐
                ▼                               ▼
         Supabase Postgres              .local-state/*.json
         (prod: entity_state,           (dry-run: no key, no net)
          sim_turn_log, sim_scenario)
                │
                ▼
   frontend/  (static SPA, polls entity_state every ~45s)
                │
                ▼
        Cloudflare Pages  ──►  🌐 public dashboard
```

**Key design choice — stateless Concordia across cron runs.** Each tick loads
durable state, re-seeds a fresh `AssociativeMemoryBank` per entity from the
transcript (shared scenario memories + formative memories + running summary +
last N turns verbatim), advances the one DUE entity with Concordia's
`basic__Entity` prefab, then makes a single structured "GM resolution" call and
persists the result. Nothing is held in memory between runs.

**Budget is HARD.** `DAILY_REQUEST_BUDGET` (default 1000, free-tier Gemini RPD)
is enforced by the scheduler. When exhausted, the sim pauses cleanly until
midnight Pacific — that is the designed fallback, never a silent failure.

Full details, the ethics notice (all scenarios are fictional LLM output), local
dry-run instructions, and the deploy checklist live in
[`projects/social-sim/README.md`](projects/social-sim/README.md).

## Live simulation

🌐 **Dashboard:** _(deployment pending — link will appear here once the frontend
is hosted and the first live tick runs.)_

The dashboard shows four fictional scenarios (a family, a startup team, a
community meeting, and a therapeutic-community ward) whose personas act on a
60-minute staggered cadence. Every scenario header carries a visible fiction
notice.
