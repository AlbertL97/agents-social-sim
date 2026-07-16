# Architecture notes

## `write` permission follows `edit`, not independent
As of opencode 1.18.x, the `write` tool cannot be enabled independently of `edit` —
setting `tools: { write: true }` with `edit: false` still resolves to `write: false`
at runtime (confirmed via `opencode debug agent <name>`). There is no way to grant
"can create new files, cannot modify existing ones" as a hard technical constraint.

Workaround used in this project: agents that need to be read-only-but-produce-output
(e.g. interaction-logger) have `edit: false` and no write access at all — they return
their output as response text, and the orchestrating primary agent (which does have
edit access) persists it to disk on their behalf.
