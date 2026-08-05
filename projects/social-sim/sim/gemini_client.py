"""Language-model + embedder clients for the simulation.

Two backends, selected by ``Config.dry_run``:

* **Gemini** (production): ``GeminiLanguageModel`` wraps the ``google-genai`` SDK
  with exponential backoff + jitter on HTTP 429 / 5xx, a HARD daily request
  budget, and minimum call spacing to respect RPM. Google Gemini is the only
  LLM provider used (per the project LLM-budget rules).

* **Stub** (dry-run / tests): ``StubLanguageModel`` returns deterministic canned
  text (and canned structured-JSON for the GM-resolution prompt) so the whole
  pipeline runs offline with no key. Auto-selected when ``GEMINI_API_KEY`` is
  unset.

Both satisfy Concordia's ``language_model.LanguageModel`` ABC
(``sample_text`` / ``sample_choice``). The embedder factory returns a
``str -> np.ndarray`` callable for Concordia's associative memory; production
uses a local scikit-learn ``HashingVectorizer`` (no API calls) so the per-turn
memory re-seed stays cheap and the Gemini budget is reserved for the LLM.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any

import numpy as np

from concordia.language_model import language_model

# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------


class BudgetExhausted(RuntimeError):
    """Raised when a call would exceed the HARD daily request budget."""


class BudgetCounter:
    """Thread-unsafe daily request counter (persisted/restored by the store).

    This is the SINGLE source of truth for the HARD daily budget. It is shared by
    the dialogue model AND the embedder (fixes #1, #2). Every Gemini request —
    including retries and Concordia-internal calls — must call ``reserve`` BEFORE
    issuing the request, so a crash/retry can never burn quota unrecorded.
    """

    def __init__(self, daily_limit: int, used: int = 0) -> None:
        self.daily_limit = int(daily_limit)
        self.used = int(used)

    def remaining(self) -> int:
        return max(0, self.daily_limit - self.used)

    def can_spend(self, n: int = 1) -> bool:
        return self.used + n <= self.daily_limit

    def reserve(self, n: int = 1) -> None:
        """Atomically reserve ``n`` requests BEFORE issuing them.

        Raises ``BudgetExhausted`` if the reservation would exceed the HARD daily
        cap, so live calls become impossible once the budget is exhausted —
        identical to how the dry-run scheduler logic behaves.
        """
        if self.used + n > self.daily_limit:
            raise BudgetExhausted(
                f"Daily request budget exhausted ({self.used}/"
                f"{self.daily_limit}); cannot reserve {n} more."
            )
        self.used += n

    def spend(self, n: int = 1) -> None:
        # Legacy post-hoc increment; the main path uses ``reserve`` (pre-request).
        self.used += n


# ---------------------------------------------------------------------------
# Stub backend (deterministic, offline)
# ---------------------------------------------------------------------------


def _is_json_request(prompt: str) -> bool:
    """Heuristic: the GM-resolution prompt asks for structured JSON output."""
    needle = prompt.lower()
    return (
        "json" in needle
        or "emotion_snapshot" in needle
        or "resolved_event" in needle
        or "state_change" in needle
    )


class StubLanguageModel(language_model.LanguageModel):
    """Deterministic stub used in dry-run. No network, no key.

    * For ordinary prompts (entity ``act``) it returns a persona-flavored line
      derived from the prompt so different entities say distinguishable things.
    * For the GM-resolution prompt (detected by JSON keywords) it returns a
      valid JSON object matching the emotional-state schema, varied deterministically
      by a hash of the prompt so successive turns differ but stay reproducible.
    """

    def __init__(self, budget: BudgetCounter | None = None) -> None:
        # When a budget is supplied (dry-run via run_tick), the stub reserves from
        # it just like the Gemini backend, so budget accounting is identical
        # between dry-run and live. In unit tests it can be left None.
        self.call_count = 0
        self._budget = budget

    def _reserve(self) -> None:
        if self._budget is not None:
            self._budget.reserve(1)

    def _hash(self, prompt: str) -> int:
        return int(hashlib.sha256(prompt.encode("utf-8")).hexdigest(), 16)

    def sample_text(
        self,
        prompt: str,
        *,
        max_tokens: int = language_model.DEFAULT_MAX_TOKENS,
        terminators: Collection[str] = language_model.DEFAULT_TERMINATORS,
        temperature: float = language_model.DEFAULT_TEMPERATURE,
        top_p: float = language_model.DEFAULT_TOP_P,
        top_k: int = language_model.DEFAULT_TOP_K,
        timeout: float = language_model.DEFAULT_TIMEOUT_SECONDS,
        seed: int | None = None,
    ) -> str:
        self._reserve()
        self.call_count += 1
        if _is_json_request(prompt):
            return self._canned_resolution_json(prompt)
        return self._canned_utterance(prompt)

    def sample_choice(
        self,
        prompt: str,
        responses: Sequence[str],
        *,
        seed: int | None = None,
    ) -> tuple[int, str, Mapping[str, Any]]:
        self._reserve()
        self.call_count += 1
        idx = self._hash(prompt) % max(1, len(responses))
        return idx, responses[idx], {}

    # -- canned content -----------------------------------------------------

    def _canned_utterance(self, prompt: str) -> str:
        h = self._hash(prompt)
        # Try to address the entity by name when it appears in the prompt.
        for line in prompt.splitlines():
            stripped = line.strip()
            if stripped and stripped[0].isupper() and len(stripped) < 40:
                pass
        templates = [
            "I hear what's being said, and I want us to find a way through this together.",
            "Let's slow down and make sure everyone's concerns are actually on the table.",
            "That lands for me, though I'm not yet ready to agree.",
            "I have a different read on this, and I think it matters.",
            "Can we name what each of us is really worried about here?",
        ]
        return templates[h % len(templates)]

    def _canned_resolution_json(self, prompt: str) -> str:
        h = self._hash(prompt)
        moods = ["cautiously engaged", "thoughtful", "mildly unsettled", "resolved to engage"]
        stresses = ["low", "medium", "high"]
        # Determine the other entities in the scene from the prompt when possible.
        others = []
        for tok in ("Tobias", "Mira", "Leo", "Renata", "Dana", "Marcus", "Priya",
                    "Theo", "Elena", "Ravi", "Sofia", "Jamal", "Iris", "Daniel",
                    "Kay", "Wren"):
            if tok in prompt and tok not in others:
                others.append(tok)
        stances = {
            name: "listening closely to where they stand"
            for name in others[:3]
        }
        obj = {
            "resolved_event": "The speaker weighed the discussion and signaled a willingness to keep talking.",
            "trigger": "responds to the most recent exchange in the shared problem.",
            "state_change": {},
            "emotion_snapshot": {
                "mood": moods[h % len(moods)],
                "stress": stresses[h % len(stresses)],
                "stances": stances,
            },
        }
        return json.dumps(obj)


class StubEmbedder:
    """Deterministic hash-based embedder for associative memory in dry-run.

    Returns a fixed-dimension, L2-normalized vector so cosine similarity in
    Concordia's memory retrieval is well-defined and stable across runs.
    """

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def __call__(self, text: str) -> np.ndarray:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        # Expand the 32-byte digest to dim bytes deterministically.
        raw = bytes((digest[i % len(digest)] + i) % 256 for i in range(self.dim))
        vec = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
            return vec


class HashingVectorizerEmbedder:
    """Local, deterministic, network-free embedder for associative memory.

    Maps text to a fixed-dimension, L2-normalized bag-of-(1,2)-grams vector via
    scikit-learn's ``HashingVectorizer``. No API calls and no rate limits, so the
    stateless re-seed-per-tick path (which adds ~50 memories per turn) stays
    cheap and the HARD Gemini budget is reserved for dialogue + GM resolution.
    Deterministic and stateless (no fit step), matching the ephemeral cron
    architecture. Retrieval is lexical, which is strong for the persona/turn
    vocabulary; swap in a neural embedder only if richer semantic recall is
    required.
    """

    def __init__(self, n_features: int = 512, ngram_range: tuple[int, int] = (1, 2)) -> None:
        from sklearn.feature_extraction.text import HashingVectorizer

        self._vectorizer = HashingVectorizer(
            n_features=n_features,
            ngram_range=ngram_range,
            norm="l2",
            alternate_sign=True,
            lowercase=True,
        )

    def __call__(self, text: str) -> np.ndarray:
        return self._vectorizer.transform([text]).toarray()[0].astype(np.float32)


# ---------------------------------------------------------------------------
# Gemini backend (production)
# ---------------------------------------------------------------------------


class GeminiLanguageModel(language_model.LanguageModel):
    """Google Gemini wrapper with backoff, budget, and RPM spacing.

    Only ``sample_text`` consumes the budget (the entity/generation path).
    ``sample_choice`` is used rarely by Concordia components; it also counts.
    """

    def __init__(
        self,
        *,
        client: Any,
        model: str,
        budget: BudgetCounter,
        min_call_spacing_seconds: float = 6.0,
        max_retries: int = 5,
        base_backoff: float = 2.0,
        rng: random.Random | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._budget = budget
        self._min_spacing = float(min_call_spacing_seconds)
        self._max_retries = int(max_retries)
        self._base_backoff = float(base_backoff)
        self._rng = rng or random.Random()
        self._last_call_ts = 0.0

    def _respect_spacing(self) -> None:
        gap = time.monotonic() - self._last_call_ts
        if gap < self._min_spacing:
            time.sleep(self._min_spacing - gap)

    def sample_text(
        self,
        prompt: str,
        *,
        max_tokens: int = language_model.DEFAULT_MAX_TOKENS,
        terminators: Collection[str] = language_model.DEFAULT_TERMINATORS,
        temperature: float = language_model.DEFAULT_TEMPERATURE,
        top_p: float = language_model.DEFAULT_TOP_P,
        top_k: int = language_model.DEFAULT_TOP_K,
        timeout: float = language_model.DEFAULT_TIMEOUT_SECONDS,
        seed: int | None = None,
    ) -> str:
        if not self._budget.can_spend():
            raise BudgetExhausted(
                f"Daily request budget exhausted ({self._budget.used}/"
                f"{self._budget.daily_limit})."
            )
        self._respect_spacing()

        config_kwargs: dict[str, Any] = {
            "temperature": temperature,
            "top_p": top_p,
            "max_output_tokens": max_tokens,
        }
        if top_k is not None:
            config_kwargs["top_k"] = top_k
        if terminators:
            config_kwargs["stop_sequences"] = list(terminators)

        from google.genai import types  # local import keeps dry-run import-free
        config = types.GenerateContentConfig(**config_kwargs)

        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self._client.models.generate_content(
                    model=self._model, contents=prompt, config=config
                )
                self._budget.spend()
                self._last_call_ts = time.monotonic()
                text = getattr(resp, "text", "") or ""
                return text
            except BudgetExhausted:
                raise
            except Exception as exc:  # noqa: BLE001 - backoff on API errors
                code = _api_error_code(exc)
                if code is None and attempt > 1:
                    raise
                if attempt > self._max_retries:
                    raise
                # Exponential backoff + full jitter. 429 -> longer base.
                base = self._base_backoff * (4 if code == 429 else 1)
                sleep = base * (2 ** (attempt - 1))
                sleep = self._rng.uniform(0, sleep)  # full jitter
                time.sleep(max(0.5, sleep))

    def sample_choice(
        self,
        prompt: str,
        responses: Sequence[str],
        *,
        seed: int | None = None,
    ) -> tuple[int, str, Mapping[str, Any]]:
        if not responses:
            return 0, "", {}
        if not self._budget.can_spend():
            raise BudgetExhausted("Daily request budget exhausted.")
        self._respect_spacing()
        config = None
        try:
            from google.genai import types
            config = types.GenerateContentConfig(temperature=0.0)
        except Exception:  # pragma: no cover
            config = None
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self._client.models.generate_content(
                    model=self._model, contents=prompt, config=config
                )
                self._budget.spend()
                self._last_call_ts = time.monotonic()
                text = (getattr(resp, "text", "") or "").strip()
                # Pick the closest response.
                idx = _best_match(text, responses)
                return idx, responses[idx], {"raw": text}
            except BudgetExhausted:
                raise
            except Exception as exc:  # noqa: BLE001
                code = _api_error_code(exc)
                if code is None and attempt > 1:
                    raise
                if attempt > self._max_retries:
                    raise
                base = self._base_backoff * (4 if code == 429 else 1)
                sleep = self._rng.uniform(0, base * (2 ** (attempt - 1)))
                time.sleep(max(0.5, sleep))


def _api_error_code(exc: Exception) -> int | None:
    """Return the HTTP status code from a google-genai APIError, else None."""
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    # Some wrapped errors expose the status on args/repr.
    msg = repr(exc)
    for token in ("429", "500", "502", "503", "504"):
        if token in msg:
            return int(token)
    return None


def _best_match(text: str, responses: Sequence[str]) -> int:
    text_l = text.lower().strip()
    for i, r in enumerate(responses):
        if r.lower().strip() in text_l or text_l in r.lower().strip():
            return i
    return 0


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def make_embedder(config) -> Callable[[str], np.ndarray]:
    """Return a ``str -> np.ndarray`` embedder for Concordia associative memory.

    Dry-run uses the deterministic ``StubEmbedder``. Production uses a local
    ``HashingVectorizerEmbedder`` (scikit-learn) — no API calls, so the
    per-turn memory re-seed (which adds ~50 memories) stays cheap and the HARD
    Gemini budget is reserved for dialogue + GM resolution only.
    """
    if config.dry_run:
        return StubEmbedder()
    return HashingVectorizerEmbedder()


def build_model(config, budget: BudgetCounter) -> language_model.LanguageModel:
    """Build the language model backend from config (Gemini or stub)."""
    if config.dry_run:
        return StubLanguageModel()
    from google import genai
    client = genai.Client(api_key=config.gemini_api_key)
    return GeminiLanguageModel(
        client=client,
        model=config.gemini_model,
        budget=budget,
        min_call_spacing_seconds=config.min_call_spacing_seconds,
    )
