# Concordia CLI quick reference

Installed automatically with `pip install gdm-concordia` as `concordia-log`.

- `concordia-log overview sim.json` — quick summary of a simulation run
- `concordia-log actions sim.json <entity>` — what an entity did
- `concordia-log context sim.json <entity> --step N` — why it acted, at a given step
- `concordia-log step sim.json <N>` — all entries for step N
- `concordia-log search sim.json "<keyword>"` — keyword search across the run
- `concordia-log memories sim.json <entity>` — an entity's stored memories
- `concordia-log entities sim.json` — list all entities (useful for scripting)
- `concordia-log components sim.json --entity <entity>` — components attached to an entity

Base64 image data is stripped from output automatically (shown as `[image: N bytes]`).
