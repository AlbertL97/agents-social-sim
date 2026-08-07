"""Centralized configuration loaded from environment variables.

All knobs the operator can tune live here. Sensible defaults make the whole
pipeline run offline in dry-run mode with no key and no Supabase project.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _get_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None or val.strip() == "":
        return default
    try:
        return int(val)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    """Resolved run configuration."""

    # --- LLM ---
    gemini_api_key: str | None
    gemini_model: str
    gemini_embedding_model: str
    dry_run: bool  # explicit override; also auto-on when key missing

    # --- Budget / cadence ---
    daily_request_budget: int
    turn_interval_seconds: int
    min_call_spacing_seconds: int
    max_calls_per_run: int
    memory_window_turns: int

    # --- Persistence ---
    supabase_url: str | None
    supabase_service_key: str | None
    supabase_anon_key: str | None
    local_state_dir: str

    @property
    def use_supabase(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)

    @classmethod
    def from_env(cls, *, force_dry_run: bool = False) -> "Config":
        key = os.environ.get("GEMINI_API_KEY") or None
        # Auto-enable dry-run when there is no key, OR when explicitly requested.
        dry_run = force_dry_run or _get_bool("DRY_RUN", False) or not key

        return cls(
            gemini_api_key=key,
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
            gemini_embedding_model=os.environ.get(
                "GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"
            ),
            dry_run=dry_run,
            daily_request_budget=_get_int("DAILY_REQUEST_BUDGET", 1000),
            turn_interval_seconds=_get_int("TURN_INTERVAL_SECONDS", 3600),
            min_call_spacing_seconds=_get_int("MIN_CALL_SPACING_SECONDS", 6),
            max_calls_per_run=_get_int("MAX_CALLS_PER_RUN", 40),
            memory_window_turns=_get_int("MEMORY_WINDOW_TURNS", 20),
            supabase_url=os.environ.get("SUPABASE_URL") or None,
            supabase_service_key=os.environ.get("SUPABASE_SERVICE_KEY") or None,
            supabase_anon_key=os.environ.get("SUPABASE_ANON_KEY") or None,
            local_state_dir=os.environ.get(
                "LOCAL_STATE_DIR", "./.local-state"
            ),
        )
