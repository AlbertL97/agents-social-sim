"""Pytest bootstrap: make the ``sim`` package importable from the project dir.

Run from ``projects/social-sim/`` with the project venv active. The whole suite
is offline (stub LLM, local JSON store) — no Gemini key and no Supabase needed.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
