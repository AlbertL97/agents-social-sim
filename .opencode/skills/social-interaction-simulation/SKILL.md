---
name: social-interaction-simulation
description: Use when building multi-agent social interaction simulators or persona-based human-AI interaction studies. Bootstraps projects with the Concordia framework (google-deepmind/concordia) instead of writing a simulation engine from scratch.
license: MIT
---

# Social interaction simulation (Concordia)

For any request to simulate agents interacting with each other, or with persona-based synthetic users, use Concordia rather than building a custom engine.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install gdm-concordia
```

Concordia needs two things beyond the library itself:
1. An LLM API for agent reasoning — reuse one of this project's already-connected providers, don't request a new key.
2. A text embedder for associative memory — `google/gemini-embedding-001` is already available through this project's Google connection. Use a local `sentence-transformers` model instead if the simulation must run fully offline.

## Core concepts

- **Entities** — the actors: player Agents, or the Game Master (GM), which narrates the environment and resolves actions (modeled on a tabletop RPG game master).
- **Components** — modular building blocks of an entity's behavior (memory, reasoning, persona traits).
- **Prefabs** — pre-assembled recipes for common agents/GMs (e.g. `basic__Entity`). Start from a prefab, don't write a custom entity from zero.
- **Associative memory + personas** — seed agent backstories via a `formative_memories_initializer` Game Master, passing per-agent `player_specific_context`. This is the mechanism for persona-based studies: one persona per dict entry, not a separate "analyzer" codebase.

## Logging into this project's research pipeline

See `references/concordia-cheatsheet.md` for the `concordia-log` CLI commands. After any simulation run, export a summary compatible with `.opencode/agent/interaction-logger.md`'s schema, so simulator runs and opencode multi-agent sessions land in the same `research-logs/` format for combined analysis later.

## Starting a new simulation project

1. Confirm with the user: number of entities/personas, scenario/environment, real-time vs batch run.
2. Scaffold from Concordia's own `examples/` directory rather than from memory of the API — find the closest example and adapt it.
3. Keep persona definitions in a separate, version-controlled file, not inline in code — `interaction-logger` and future analysis reference this file directly.
