# agents-social-sim

A live, always-on laboratory for **social behavior between AI agents.** Four
fictional groups — a family, a startup team, a research group, and a therapeutic
community — are each played by AI personas (sketched with the Big Five / OCEAN
model) that converse with each other on a staggered cadence, and the resulting
group dynamics stream to a public dashboard you can watch unfold in real time.

> 🌐 **Watch the live simulation → <https://albertl97.github.io/agents-social-sim/>**

---

## Why study social behavior among AI systems?

Most evaluation of large language models is **solitary and single-turn**: one
model answering one prompt, scored in isolation. But AI systems are increasingly
deployed in settings where they do not act alone — they negotiate, collaborate,
moderate, advise, and coordinate, with other agents and with people.

The behaviors that matter most in those settings are **emergent and relational**:
persuasion and resistance, trust and betrayal, coalition formation, the rise and
erosion of norms, conflict that escalates or de-escalates, the way a group
converges on — or fails to converge on — a shared decision. None of them appear
when you probe a single model once. They surface only when **multiple agents act
on each other over time**, which makes them hard to measure and increasingly hard
to ignore. As autonomous agents take on real roles, group-level dynamics become
a safety and alignment concern, not a curiosity — polarization cascades,
sycophancy loops, tacit collusion, and the slow erosion of trust are properties
of the *collective*, invisible to any single-agent benchmark.

**Multi-agent social simulation is a cheap, controllable laboratory for exactly
these phenomena.** Hold the "world" fixed and vary one thing at a time — a
persona's traits, the rules of conversation, who knows what — then watch how the
group's behavior changes. It is reproducible and ethical (no human subjects), and
it can be observed continuously rather than in one-off transcripts. This project
builds the always-on plumbing to run such experiments and observe them live,
grounded in Google DeepMind's
[Concordia](https://github.com/google-deepmind/concordia) multi-agent framework.

> **Watch it happen.** The four scenarios are running right now at
> **<https://albertl97.github.io/agents-social-sim/>** — new turns appear on the
> dashboard as the daily model budget allows.

> **Ethics notice.** Every scenario — including the therapeutic-community ward —
> is an **entirely fictional simulation produced by language models**. No real
> people, institutions, patients, or clinical/scientific/business practice are
> depicted. The notice is shown visibly on the dashboard, never buried.

---

## How this was built (a testbed for agentic coding)

Beyond the research goal above, this repository is kept as an honest artifact of
*how* it was built. The whole system — architecture, the
stateless-Concordia-over-cron design, the budget/scheduler logic, the dashboard,
and a round of live debugging — was specified, written, and repaired by **GLM-5.2
driving [opencode](https://opencode.ai)**, with a human in the loop for goals and
go/no-go decisions only. The commit history shows the model designing the system,
hardening it across several iterations, and diagnosing a subtle live failure (a
silent daily-budget drain that left the sim at "one turn ever") from raw GitHub
Actions logs. A central question the project probes: **how well does a single
coding model hold a non-trivial, long-horizon system together** — across
cold-start state reconstruction, rate-limit economics, and a public deploy — when
it can only act through ephemeral tool calls?

opencode also lets the primary agent **delegate** focused subtasks to
purpose-built subagents rather than doing everything inline. That shaped how this
was built:

- An **explorer** agent mapped the existing code and conventions before any code
  was written, so new modules matched the repo's style and imports.
- A **tester** agent owns the offline pytest suite (`projects/social-sim/tests/`)
  and is the gate the live cron run re-runs every tick — a regression introduced
  anywhere is caught before it reaches production.
- An **interaction logger** records the agent workflow itself (kept read-only by
  design: it returns its output and the primary agent persists it), feeding the
  meta-study of *how* the system was built.

Delegation here is less about raw speed and more about **separation of
concerns**: each agent has a narrow, inspectable job, and the primary agent
orchestrates. The `.opencode/` and `.agents/` configuration in this repo is part
of that setup.

---

## The simulation, in brief

There is **no always-on server.** GitHub Actions fires an ephemeral `advance.py`
on a schedule; each run loads persisted state from Supabase, advances whichever
entity turns are **due** (a HARD daily budget + a round-robin cadence across the
four scenarios), and exits. The frontend is a static SPA that polls Supabase
directly.

```
            on a schedule
   GitHub Actions (cron) ──► advance.py  (ephemeral, single tick)
                                 │
                                 ▼
                          sim/pipeline.py
                                 │
         ┌───────────────────────┼────────────────────────────┐
         ▼                       ▼                            ▼
   sim/scheduler.py       sim/concordia_engine.py      sim/gemini_client.py
   due/budget math +      stateless entity +           Gemini dialogue
   round-robin across     lean turn advance            (HARD daily budget,
   scenarios              (re-seeded from transcript)   backoff + jitter)
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
    frontend/  (static SPA, polls every ~45s)
                 │
                 ▼
       GitHub Pages  ──►  🌐 public dashboard
```

**Key design choice — stateless Concordia across cron runs.** Each tick
re-seeds a fresh `AssociativeMemoryBank` per entity from the durable transcript
(shared scenario memories + formative memories + a running summary + the last N
turns verbatim), advances the one due entity with Concordia's `basic__Entity`
prefab, then makes a single structured "GM resolution" call and persists the
result. Nothing is held in memory between runs.

**Budget is HARD.** Gemini's free tier is rate-limited by requests per day
(RPD). The scheduler enforces `DAILY_REQUEST_BUDGET` and round-robins turns
across all four scenarios so the dashboard fills evenly; when the budget is
spent, the sim pauses cleanly until midnight Pacific and later runs no-op fast
rather than wasting retries. (This is the designed fallback — never a silent
failure; the fix for the silent-drain bug is documented in the commit history.)

Full architecture, the ethics notice, local dry-run instructions, configuration
reference, and the deploy checklist live in
[`projects/social-sim/README.md`](projects/social-sim/README.md).

---

## Projects

| Path | What it is |
|------|------------|
| [`projects/social-sim/`](projects/social-sim/) | Live multi-agent social simulation dashboard (Concordia + Gemini + Supabase + GitHub Pages). |
| [`projects/word_frequency/`](projects/word_frequency/) | Small word-frequency utility + unit tests. |

---

## Run it locally (dry-run, no key, no Supabase)

```bash
cd projects/social-sim
uv venv .venv --python 3.12          # or: python3 -m venv .venv
uv pip install -r requirements.txt   # or: .venv/bin/pip install -r requirements.txt
. .venv/bin/activate

python advance.py --dry-run                       # one scheduler tick (local JSON)
python advance.py --dry-run --once family Renata  # advance one specific turn
python -m pytest tests/ -q                        # offline test suite
```

Dry-run auto-enables whenever `GEMINI_API_KEY` is unset: a deterministic stub
LLM + local JSON store, no network.

---

## Tech stack

Concordia (multi-agent) · Google Gemini (`gemini-3.5-flash-lite`, free tier) ·
Supabase (free Postgres) · GitHub Actions (cron) · GitHub Pages (static
dashboard) · built with [opencode](https://opencode.ai) + GLM-5.2.
