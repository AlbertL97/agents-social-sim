# Social Sim — live multi-agent social simulation dashboard

Four independent **Concordia** multi-agent simulations run on a staggered cycle
and feed a live public dashboard. There is **no always-on server**: GitHub
Actions fires an ephemeral `advance.py` every ~10 minutes; each run loads
persisted state from Supabase, advances whichever scenario/entity is DUE, and
exits. The frontend is a static SPA that polls Supabase directly.

> **Ethics notice (non-negotiable).** All four scenarios — including the
> psychiatric ward — are **entirely fictional simulations produced by language
> models**. They do not depict real people, institutions, patients, or
> clinical/scientific/business practice. The ward scenario is a fictional
> **therapeutic-community** process simulation (Maxwell Jones tradition),
> kept strictly process-oriented — no symptoms, diagnoses, self-harm, or crisis
> content. This notice is shown visibly on the landing page and in every
> scenario header, never buried in a footer.

---

## What's here

```
projects/social-sim/
  personas.md            # Source of truth: 4 scenarios × 4 personas (Big Five). DO NOT edit.
  advance.py             # Cron entry point (GitHub Actions runs this).
  sim/
    config.py            # Env-driven configuration (budget, cadence, backend).
    personas.py          # Parse personas.md -> ScenarioDef/EntityDef.
    gemini_client.py     # GeminiModel (backoff + HARD budget) + StubModel + embedders.
    emotional_state.py   # Parse/validate the structured GM-resolution JSON.
    state_store.py       # Supabase + local-JSON persistence backends.
    scheduler.py         # Due/budget math with 60-min staggered cadence.
    concordia_engine.py  # Stateless entity/memory reconstruction + lean turn advance.
    pipeline.py          # Orchestrates one cron tick.
  tests/                 # Offline (stub LLM, local JSON) — `pytest`.
  frontend/              # Static dashboard SPA (index.html + app.js + styles.css).
  supabase/schema.sql    # Tables + RLS (run in the Supabase SQL editor once).
  requirements.txt
  .env.example
.github/workflows/social-sim.yml   # Cron `*/10 * * * *` + workflow_dispatch.
```

The sim logs live **only** in Supabase (or local JSON). They are never written
into the repo's `research-logs/` folder.

---

## How it works

### Stateless Concordia across cron runs (the hard part)

Concordia normally holds entity associative memory in-process for a long run.
Our architecture is **ephemeral per tick**, so simulation state must survive
across runs:

1. **Cold start** (first tick per scenario): formative memories are seeded from
   the persona definitions (`player_specific_context` rendered as memories).
   In production with a real Gemini model and budget, the Concordia
   `formative_memories_initializer` Game Master enriches them with LLM-generated
   backstory episodes. In dry-run, deterministic persona-derived memories are
   used. All 16 `entity_state` rows are seeded so the dashboard is populated
   immediately.
2. **Warm tick**: for each DUE entity, all 4 entities in the scenario are
   reconstructed by building a fresh `AssociativeMemoryBank` and **re-seeding**
   it from the durable transcript: shared scenario memories + the entity's
   formative memories + a **running summary** of earlier turns + the **last N
   turns verbatim**. This is the idiomatic Concordia re-seed path (`bank.add`
   uses the embedder for retrieval).
3. The DUE entity's turn is advanced with Concordia's own `basic__Entity`
   prefab (its `.act()` runs the full persona component stack — self/situation/
   person perception + memory). Then **one** structured "GM resolution" model
   call returns the resolved event + trigger + state change + the speaker's
   emotional snapshot as JSON.
4. Results are persisted: an append-only `sim_turn_log` row, an upserted
   `entity_state` row for the speaker, and updated `sim_scenario` context.

**Memory-window cap (budget).** The working-memory window fed to each entity is
capped (`MEMORY_WINDOW_TURNS`, default 20: last N turns verbatim + a short
running summary). **Everything** remains durable in `sim_turn_log`; the cap only
bounds the in-context window to stay within the token budget.

**Why a lean resolution instead of the full generic-GM loop?** The full
Concordia Sequential generic-GM loop makes ~8–12 model calls per turn (make
observations for all entities, next-acting, multi-step event-resolution thought
chains, termination checks). At 16 turns/hour that would exhaust the free-tier
daily budget in hours. To keep the 60-min cadence feasible under the **HARD**
daily budget, the per-turn advance uses Concordia's entity `.act()` (the persona/
memory mechanism) plus **one** structured resolution call folding resolution +
emotional extraction together. This leans on Concordia's memory/persona
mechanisms rather than reimplementing them; it is a deliberate, budget-driven
simplification of the GM loop, documented here and flagged in the final report.

### Scheduler + budget

- **60-minute staggered cadence**: each entity speaks ~once per 60-min cycle;
  the 4 scenarios get per-scenario stagger offsets so they don't all fire at the
  same cron tick.
- **`DAILY_REQUEST_BUDGET` (default 1000) is a HARD daily cap** the scheduler
  enforces. RPD, not RPM, is the binding constraint for 24/7 operation. The
  counter resets at midnight Pacific (Gemini's RPD reset). When exhausted, the
  scheduler stops cleanly; entities simply wait for the next day.
- Exponential backoff + full jitter on HTTP 429/5xx; never retry immediately.
- Per-run cap (`MAX_CALLS_PER_RUN`) and minimum call spacing (`MIN_CALL_SPACING_SECONDS`).
- Overlap guard: a GitHub Actions `concurrency` group **plus** a DB run-lock row
  (`sim_meta`, with TTL).

### Emotional state + stance extraction

After each turn, the structured GM resolution returns the speaker's snapshot
(`mood`: short phrase; `stress`: low/med/high; `stances`: one line toward each of
the other 3 entities) plus any explicit `state_change` it caused in another
entity. This is folded into the single resolution call (no separate extraction
call) to conserve budget. Both are written to `sim_turn_log`; the snapshot
upserts the speaker's `entity_state` row that drives the dashboard.

---

## Run locally (dry-run, no key, no Supabase)

```bash
cd projects/social-sim
uv venv .venv --python 3.12          # or: python3 -m venv .venv
uv pip install -r requirements.txt   # or: .venv/bin/pip install -r requirements.txt
. . .venv/bin/activate

python advance.py --dry-run                       # one scheduler tick (local JSON)
python advance.py --dry-run --once family Renata  # advance one specific turn
python -m pytest tests/ -q                        # offline test suite
```

Dry-run auto-enables whenever `GEMINI_API_KEY` is unset. It uses a deterministic
stub LLM + stub embedder and writes to `.local-state/` (JSON files mirroring the
Supabase tables). No network, no key.

Inspect the local output:

```bash
cat .local-state/entity_state.json   # the dashboard feed
cat .local-state/sim_turn_log.jsonl  # the append-only research log
```

Open the dashboard skeleton:

```bash
# Just open frontend/index.html in a browser. With no Supabase config it shows
# the skeleton + the (always-visible) fiction banner.
```

---

## Deploy

The deployer's checklist (do **not** enable billing on the Gemini project):

1. **Supabase (Free Postgres).** Create a project, open the SQL editor, and run
   `projects/social-sim/supabase/schema.sql`. Note the **Project URL**, the
   **service_role key** (for writes, used only in Actions), and the **anon key**
   (for the read-only frontend).
2. **GitHub secrets/variables** (repo → Settings → Secrets and variables → Actions):
   - Secrets: `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`.
   - Optional variables (defaults shown): `GEMINI_MODEL=gemini-3.6-flash`,
     `GEMINI_EMBEDDING_MODEL=gemini-embedding-001`, `DAILY_REQUEST_BUDGET=1000`,
     `TURN_INTERVAL_SECONDS=3600`, `MIN_CALL_SPACING_SECONDS=6`,
     `MAX_CALLS_PER_RUN=40`, `MEMORY_WINDOW_TURNS=20`.
3. **Make the repo public** — free GitHub Actions requires a public repo for the
   `schedule` trigger to fire. (Private repos do not run scheduled workflows on
   the free plan.) The `workflow_dispatch` trigger works regardless.
4. **Frontend → Cloudflare Pages** (or any static host). Set the build output to
   `projects/social-sim/frontend/`. Fill `window.SOCIAL_SIM_CONFIG` in
   `index.html` with the Supabase URL + **anon** key (never the service key).
   The dashboard polls `entity_state` every ~45s.

Do **not** commit secrets, the venv, or real credentials. `.gitignore` already
excludes `.venv/`, `.local-state/`, and `.env`.

---

## Configuration reference

See `.env.example` for every knob. The most important:

| Var | Default | Meaning |
|-----|---------|---------|
| `GEMINI_API_KEY` | _(unset → dry-run)_ | Google Gemini key. **Do not enable billing.** |
| `GEMINI_MODEL` | `gemini-3.6-flash` | Dialogue model (Flash family). |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Embeddings for associative memory. |
| `DAILY_REQUEST_BUDGET` | `1000` | HARD daily cap. |
| `TURN_INTERVAL_SECONDS` | `3600` | Per-entity turn interval (60-min cycle). |
| `MIN_CALL_SPACING_SECONDS` | `6` | Minimum spacing between Gemini calls (RPM). |
| `MAX_CALLS_PER_RUN` | `40` | Cap per cron run. |
| `MEMORY_WINDOW_TURNS` | `20` | Capped working-memory window per entity. |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | _(unset → local JSON)_ | Persistence backend. |

---

## Budget & cadence rationale

Free-tier Gemini is rate-limited by **requests per day** (RPD), which is the
binding constraint for 24/7 operation. With 16 speaking entities and a 60-min
cadence, the design point is comfortably under the daily budget with margin for
retries. The budget is **HARD**: if per-turn cost makes the target cadence
infeasible on a given day, the scheduler simply advances fewer turns and entities
wait — that is the designed fallback, never a silent failure. Raise
`DAILY_REQUEST_BUDGET` (or the cadence interval) to tune.
