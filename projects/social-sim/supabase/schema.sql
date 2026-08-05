-- Social-sim schema for Supabase (Free Postgres).
--
-- Run this in the Supabase SQL editor for your project BEFORE the first
-- `advance.py` run. It creates four tables and a read-only RLS policy:
--
--   entity_state   — one row per (scenario_id, entity_id). UPSERTed each turn.
--                    Drives the fast dashboard.
--   sim_turn_log   — APPEND-ONLY research instrument.
--   sim_scenario   — per-scenario reconstruction context (summary, turn count,
--                    persisted formative memories, initialized flag).
--   sim_meta       — daily request counter (resets at midnight Pacific) + an
--                    ephemeral run-lock row with TTL.
--
-- Writes happen ONLY via the service_role key (used in GitHub Actions).
-- The public static frontend reads both entity_state and sim_turn_log with the
-- anon key under RLS (SELECT-only).
--
-- These sim logs are SEPARATE from the repo's research-logs/ folder.

-- Required for gen_random_uuid() on older Supabase versions.
create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- entity_state
-- ---------------------------------------------------------------------------
create table if not exists public.entity_state (
  scenario_id   text        not null,
  entity_id     text        not null,
  mood          text        not null default '',
  stress        text        not null default 'medium'
                 check (stress in ('low','medium','high')),
  stances       jsonb       not null default '{}'::jsonb,
  last_utterance text       not null default '',
  last_turn_ts  timestamptz,
  updated_at    timestamptz not null default now(),
  primary key (scenario_id, entity_id)
);

comment on table public.entity_state is
  'Latest per-entity emotional state for the live dashboard (UPSERTed each turn).';

-- ---------------------------------------------------------------------------
-- sim_turn_log  (append-only)
-- ---------------------------------------------------------------------------
create table if not exists public.sim_turn_log (
  turn_id          uuid        primary key default gen_random_uuid(),
  turn_index       integer     not null,
  ts               timestamptz not null default now(),
  scenario_id      text        not null,
  entity_id        text        not null,
  utterance        text        not null default '',
  trigger          jsonb       not null default '{}'::jsonb,
  state_change     jsonb       not null default '{}'::jsonb,
  emotion_snapshot jsonb       not null default '{}'::jsonb,
  model            text        not null default '',
  raw_meta         jsonb       not null default '{}'::jsonb
);

create index if not exists sim_turn_log_scenario_idx
  on public.sim_turn_log (scenario_id, turn_index);

comment on table public.sim_turn_log is
  'Append-only research log of every entity turn (full utterance, trigger, '
  'state_change, emotion_snapshot, model, raw_meta).';

-- ---------------------------------------------------------------------------
-- sim_scenario  (reconstruction context, one row per scenario)
-- ---------------------------------------------------------------------------
create table if not exists public.sim_scenario (
  scenario_id        text     primary key,
  running_summary    text     not null default '',
  turn_count         integer  not null default 0,
  formative_memories jsonb    not null default '{}'::jsonb,
  initialized        boolean  not null default false,
  updated_ts         timestamptz not null default now()
);

comment on table public.sim_scenario is
  'Per-scenario stateless reconstruction context: running summary, turn count, '
  'persisted formative memories, initialized flag.';

-- ---------------------------------------------------------------------------
-- sim_meta  (daily budget counter + run lock)
-- ---------------------------------------------------------------------------
create table if not exists public.sim_meta (
  id            text        primary key,            -- 'budget' | 'run_lock'
  budget_date   text,                               -- Pacific date (YYYY-MM-DD)
  used          integer     not null default 0,
  running       boolean,                            -- run-lock flag
  running_since double precision                     -- epoch seconds
);

comment on table public.sim_meta is
  'Daily request counter (resets at midnight Pacific per Gemini RPD reset) and '
  'an ephemeral run-lock row with TTL to guard against overlapping cron runs.';

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
alter table public.entity_state   enable row level security;
alter table public.sim_turn_log   enable row level security;
alter table public.sim_scenario   enable row level security;
alter table public.sim_meta       enable row level security;

-- The anon role (public frontend) can SELECT entity_state and sim_turn_log only.
drop policy if exists "anon read entity_state" on public.entity_state;
create policy "anon read entity_state"
  on public.entity_state for select
  to anon
  using (true);

drop policy if exists "anon read sim_turn_log" on public.sim_turn_log;
create policy "anon read sim_turn_log"
  on public.sim_turn_log for select
  to anon
  using (true);

-- The service_role bypasses RLS entirely (used by GitHub Actions for writes),
-- so no insert/update policies are needed for it. sim_scenario and sim_meta are
-- fully service-role-only (no anon policy => anon gets nothing).
