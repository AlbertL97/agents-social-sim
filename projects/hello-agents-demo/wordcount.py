"""Word frequency counter.

This module provides a small utility to count the frequency of words in a
piece of text. It is intentionally dependency-free, relying only on the
Python standard library.
"""

from __future__ import annotations

import re

# Matches a word: a run of Unicode word characters that may contain internal
# apostrophes (ASCII ' or typographic ’). Because each apostrophe must be
# followed by more word characters, a word cannot start or end with an
# apostrophe, so leading/trailing quotes are treated as punctuation and
# ignored. This keeps contractions such as "don't" as a single token while
# stripping surrounding punctuation like "'hello'".
_WORD_RE = re.compile(r"\w+(?:['']\w+)*", re.UNICODE)


def word_frequency(text: str) -> dict[str, int]:
    """Return a case-insensitive count of words in ``text``.

    A *word* is a run of Unicode word characters that may contain internal
    apostrophes, so contractions such as ``"don't"`` count as a single word.
    Leading and trailing apostrophes and other punctuation are stripped, so
    ``"'hello'"`` becomes ``"hello"``.

    Matching is case-insensitive using Unicode case folding
    (:meth:`str.casefold`), which is more aggressive than ``str.lower``: it
    folds ``"WORD"`` and ``"word"`` together and also handles cases such as
    ``"Straße"`` matching ``"strasse"``.

    Args:
        text: The input text to analyze.

    Returns:
        A mapping of each case-folded word to the number of times it appears.
        An empty input (or an input with no words) returns an empty dict.
    """
    if not text:
        return {}

    counts: dict[str, int] = {}
    for match in _WORD_RE.findall(text):
        word = match.casefold()
        counts[word] = counts.get(word, 0) + 1
    return counts
