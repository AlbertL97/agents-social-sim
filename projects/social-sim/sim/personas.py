"""Parse ``personas.md`` into structured scenario/entity definitions.

``personas.md`` is the single source of truth (per the project brief, it must
not be changed). This module turns its structured Markdown into dataclasses the
rest of the pipeline consumes: 4 scenarios x 4 entities = 16 personas, each with
the full Big Five (OCEAN) model, formative backstory, relationships, and the
starting emotional-state snapshot that seeds the dashboard.

The parser is tailored to the exact Markdown structure of ``personas.md``
(scenario headers ``## Scenario N - Title``, entity headers ``### N. Name - Role``,
bold-labeled bullet blocks where the colon sits *inside* the bold, e.g.
``**Personality (Big Five):**``). It is covered by tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Canonical short ids for the four scenarios, derived from their titles.
SCENARIO_IDS: dict[str, str] = {
    "family household": "family",
    "corporation": "corporation",
    "university research group": "university",
    "psychiatric ward": "ward",  # therapeutic community
}

BIG_FIVE_FACETS = (
    "openness",
    "conscientiousness",
    "extraversion",
    "agreeableness",
    "neuroticism",
)

VALID_STRESS = {"low", "medium", "high"}


def normalize_stress(raw: str) -> str:
    """Bucket a free-form stress level into {low, medium, high}.

    Personas use compounds like 'low-medium' or 'medium-high'. We take the
    dominant tendency: any 'high' -> high, any 'low' -> low, else medium.
    """
    s = raw.strip().lower()
    if "high" in s:
        return "high"
    if "low" in s:
        return "low"
    return "medium"


@dataclass
class EntityDef:
    name: str
    scenario_id: str
    scenario_title: str
    role: str
    big_five: dict[str, str] = field(default_factory=dict)
    big_five_behaviors: dict[str, str] = field(default_factory=dict)
    formative_backstory: str = ""
    communication_style: str = ""
    goals: str = ""
    initial_relationships: dict[str, str] = field(default_factory=dict)
    mood: str = ""
    stress_raw: str = "medium"
    stances: dict[str, str] = field(default_factory=dict)

    @property
    def stress(self) -> str:
        return normalize_stress(self.stress_raw)

    @property
    def persona_context(self) -> str:
        """The free-text persona, used as ``player_specific_context``.

        This is fed to Concordia's ``formative_memories_initializer`` Game Master
        (and used directly to seed formative memories in dry-run). It preserves
        the persona's voice and the process-oriented framing required by ethics.
        """
        parts = [f"Name: {self.name}", f"Role: {self.role}"]
        if self.big_five:
            facets = ", ".join(
                f"{f.capitalize()}: {self.big_five[f]}" for f in BIG_FIVE_FACETS
                if f in self.big_five
            )
            parts.append(f"Personality (Big Five): {facets}")
        for label, text in (
            ("Formative backstory", self.formative_backstory),
            ("Communication style", self.communication_style),
            ("Goals", self.goals),
        ):
            if text:
                parts.append(f"{label}: {text}")
        return "\n".join(parts)


@dataclass
class ScenarioDef:
    id: str
    title: str
    environment: str
    shared_problem: str
    ethics_notice: str = ""
    entities: list[EntityDef] = field(default_factory=list)


def _strip_emphasis(text: str) -> str:
    return re.sub(r"\*+|_+", "", text).strip()


def _find_scenario_id(title: str) -> str:
    t = title.lower()
    for key, sid in SCENARIO_IDS.items():
        if key in t:
            return sid
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-") or "scenario"


def _clean_inline(text: str) -> str:
    """Collapse whitespace for a captured inline block."""
    return re.sub(r"\s+", " ", text).strip()


def _parse_big_five(block: str) -> tuple[dict[str, str], dict[str, str]]:
    """Extract level + behavioral sentence for each Big Five facet sub-bullet.

    Sub-bullet shape: ``- *Openness:* **Medium** - behavioral sentence.`` Note
    the colon sits *inside* the italics (``*Openness:*``).
    """
    levels: dict[str, str] = {}
    behaviors: dict[str, str] = {}
    pattern = re.compile(
        r"-\s*\*+([A-Za-z]+)\s*:\*+\s*\*+([^*]+?)\*+\s*[,;\u2014:\-]?\s*([^\n]+)"
    )
    for m in pattern.finditer(block):
        facet = m.group(1).strip().lower()
        level = _strip_emphasis(m.group(2)).strip().lower()
        sentence = _strip_emphasis(m.group(3)).strip()
        if facet in BIG_FIVE_FACETS:
            levels[facet] = level
            behaviors[facet] = sentence
    return levels, behaviors


def _parse_relationships(block: str) -> dict[str, str]:
    """Parse '- *Name:* description' sub-bullets into {name: description}.

    The colon sits inside the italics (``*Tobias:*``).
    """
    out: dict[str, str] = {}
    pattern = re.compile(
        r"-\s*\*+([A-Z][\w\- ]*?)\s*:\*+\s*(.+?)(?=\n\s*-\s*\*+|\Z)",
        re.DOTALL,
    )
    for m in pattern.finditer(block):
        name = _strip_emphasis(m.group(1)).strip().strip(".")
        desc = _clean_inline(m.group(2))
        # Keep only plausible single proper-name targets.
        if name and len(name.split()) <= 3:
            out[name] = desc
    return out


def _unquote(text: str) -> str:
    """Strip surrounding quotes/whitespace from a captured phrase."""
    t = text.strip().strip("\u201c\u201d\"'")
    return t.strip()


def _parse_emotional_state(block: str) -> tuple[str, str, dict[str, str]]:
    """Parse the 'Emotional-state model (starting values)' line."""
    mood = ""
    stress_raw = "medium"
    stances: dict[str, str] = {}

    mood_m = re.search(r"mood\s*:\s*\*+([^*]+?)\*+", block, re.IGNORECASE)
    if mood_m:
        mood = _unquote(mood_m.group(1))

    stress_m = re.search(r"stress\s*:\s*\*+([^*]+?)\*+", block, re.IGNORECASE)
    if stress_m:
        stress_raw = _strip_emphasis(stress_m.group(1)).strip().lower()

    for m in re.finditer(
        r"stance\s+toward\s+([^;\-:\u2014]+?)\s*[-\u2014]\s*\*+([^*]+?)\*+",
        block,
    ):
        target = m.group(1).strip()
        phrase = _unquote(m.group(2))
        stances[target] = phrase
    return mood, stress_raw, stances


def _extract_block(entity_text: str, label: str) -> str:
    """Extract text under a '**Label:**' bullet up to the next top-level bullet.

    The bold label may carry a parenthetical and the colon sits *inside* the
    bold (e.g. ``**Emotional-state model (starting values):**``). We allow any
    non-asterisk text between the literal label and the closing ``**``.
    """
    pattern = re.compile(
        r"\*+\s*" + re.escape(label) + r"[^*\n]*\*+\s*:?\s*(.+?)(?=\n-\s*\*\*|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(entity_text)
    return m.group(1).strip() if m else ""


def _parse_entity(
    raw_header: str, body: str, scenario_id: str, scenario_title: str
) -> EntityDef:
    # raw_header like "### 1. Renata - Mother, works part-time"
    m = re.match(r"###\s+\d+\.\s*(.+)", raw_header)
    title_part = m.group(1).strip() if m else raw_header
    for sep in (" - ", " \u2014 ", " – "):
        if sep in title_part:
            name, role = title_part.split(sep, 1)
            break
    else:
        name, role = title_part, ""
    name = name.strip()
    role = role.strip()

    big_five_block = _extract_block(body, "Personality (Big Five)")
    levels, behaviors = _parse_big_five(big_five_block)

    rel_block = _extract_block(body, "Initial relationships")
    relationships = _parse_relationships(rel_block)

    emo_block = _extract_block(body, "Emotional-state model")
    mood, stress_raw, stances = _parse_emotional_state(emo_block)

    return EntityDef(
        name=name,
        scenario_id=scenario_id,
        scenario_title=scenario_title,
        role=role,
        big_five=levels,
        big_five_behaviors=behaviors,
        formative_backstory=_clean_inline(_extract_block(body, "Formative backstory")),
        communication_style=_clean_inline(
            _extract_block(body, "Communication style")
        ),
        goals=_clean_inline(_extract_block(body, "Goals")),
        initial_relationships=relationships,
        mood=mood,
        stress_raw=stress_raw,
        stances=stances,
    )


# Split the document into scenario chunks. Each starts at a "## Scenario" header.
_SCENARIO_SPLIT = re.compile(r"(?=^##\s+Scenario\s+\d+\s*[-\u2014]\s)", re.MULTILINE)
_SCENARIO_HDR = re.compile(r"^##\s+Scenario\s+\d+\s*[-\u2014]\s*(.+)$", re.MULTILINE)
_ENTITY_SPLIT = re.compile(r"(?=^###\s+\d+\.\s)", re.MULTILINE)
_ENTITY_HDR = re.compile(r"^###\s+\d+\.\s*.+$", re.MULTILINE)


def _parse_scenario(chunk: str) -> ScenarioDef:
    lines = chunk.splitlines()
    title = "Unknown"
    for ln in lines:
        hm = _SCENARIO_HDR.match(ln)
        if hm:
            title = hm.group(1).strip()
            break
    sid = _find_scenario_id(title)

    # Ethics blockquotes (the ward scenario's process-oriented fiction notice).
    ethics_lines = [
        ln.lstrip(">").strip()
        for ln in lines
        if ln.strip().startswith(">")
    ]
    ethics_notice = " ".join(e for e in ethics_lines if e).strip()

    # Environment text: after the "**Environment ...:**" label up to "**Shared problem".
    env = ""
    m_env = re.search(
        r"\*\*\s*Environment[^:]*:\*\*\s*(.+?)(?=\*\*\s*Shared problem|\Z)",
        chunk,
        re.DOTALL | re.IGNORECASE,
    )
    if m_env:
        env = _clean_inline(m_env.group(1))

    # Shared problem text: after "**Shared problem...:**" up to the first entity header.
    problem = ""
    m_prob = re.search(
        r"\*\*\s*Shared problem[^:]*:\*\*\s*(.+?)(?=^###\s+\d+\.|\Z)",
        chunk,
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    )
    if m_prob:
        problem = _clean_inline(m_prob.group(1))

    scenario = ScenarioDef(
        id=sid,
        title=title,
        environment=env,
        shared_problem=problem,
        ethics_notice=ethics_notice,
    )

    # Split out entity subsections.
    parts = _ENTITY_SPLIT.split(chunk)
    for part in parts:
        if not _ENTITY_HDR.match(part):
            continue
        first_line = part.splitlines()[0]
        body = "\n".join(part.splitlines()[1:])
        scenario.entities.append(
            _parse_entity(first_line, body, sid, title)
        )

    return scenario


def parse_personas(text: str) -> list[ScenarioDef]:
    """Parse the full personas Markdown into a list of ScenarioDef."""
    chunks = _SCENARIO_SPLIT.split(text)
    scenarios: list[ScenarioDef] = []
    for chunk in chunks:
        if not _SCENARIO_HDR.match(chunk):
            continue
        scenarios.append(_parse_scenario(chunk))
    return scenarios


def load_personas(path: str | Path) -> list[ScenarioDef]:
    """Read and parse the personas file."""
    return parse_personas(Path(path).read_text(encoding="utf-8"))


def all_entities(scenarios: list[ScenarioDef]) -> list[EntityDef]:
    """Flatten scenarios into a single list of entity definitions."""
    out: list[EntityDef] = []
    for s in scenarios:
        out.extend(s.entities)
    return out
