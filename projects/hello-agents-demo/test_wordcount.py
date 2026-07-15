"""Unit tests for the :mod:`wordcount` module.

These tests use only the standard-library :mod:`unittest` framework and can
be run in either of the following ways:

* Directly::

      python projects/hello-agents-demo/test_wordcount.py

* Via ``unittest`` discovery from inside the script's directory::

      cd projects/hello-agents-demo
      python -m unittest test_wordcount

  (or ``python -m unittest`` to discover every test module in the folder).
"""

from __future__ import annotations

import os
import sys
import unittest

# Make the sibling ``wordcount`` module importable regardless of the current
# working directory, so that the tests can be executed from anywhere.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wordcount import word_frequency  # noqa: E402  (import after sys.path tweak)


class TestWordFrequency(unittest.TestCase):
    """Tests covering the documented behaviour of :func:`word_frequency`."""

    def test_empty_string_returns_empty_dict(self) -> None:
        """An empty string must produce an empty mapping."""
        self.assertEqual(word_frequency(""), {})

    def test_string_with_no_words_returns_empty_dict(self) -> None:
        """A string containing only punctuation/whitespace has no words."""
        self.assertEqual(word_frequency("   ... , !!!  "), {})

    def test_repeated_words(self) -> None:
        """Repeated words should each be counted correctly."""
        text = "the cat and the dog and the bird"
        expected = {"the": 3, "cat": 1, "and": 2, "dog": 1, "bird": 1}
        self.assertEqual(word_frequency(text), expected)

    def test_punctuation_handling(self) -> None:
        """Punctuation attached to words must be ignored."""
        text = "Hello, world! Hello..."
        expected = {"hello": 2, "world": 1}
        self.assertEqual(word_frequency(text), expected)

    def test_case_insensitivity(self) -> None:
        """Mixed-case words should fold to a single lowercase key."""
        text = "Word WORD word wOrD"
        self.assertEqual(word_frequency(text), {"word": 4})

    def test_contractions_preserve_internal_apostrophe(self) -> None:
        """Internal apostrophes are kept, trailing/leading ones are stripped."""
        # "don't" keeps its internal apostrophe, while the dangling apostrophe
        # at the end of "believin'" is stripped to give "believin".
        self.assertEqual(
            word_frequency("don't stop believin'"),
            {"don't": 1, "stop": 1, "believin": 1},
        )

    def test_surrounding_quotes_are_stripped(self) -> None:
        """Leading/trailing apostrophes and quotes are punctuation, not word."""
        self.assertEqual(word_frequency("'quoted'"), {"quoted": 1})

    def test_unicode_case_folding(self) -> None:
        """Full Unicode case folding collapses e.g. Straße and STRASSE.

        ``str.casefold`` folds ``ß`` to ``ss``, so both forms map to the same
        key ``"strasse"`` (note: not ``"straße"``). With plain ``str.lower``
        these would *not* collapse.
        """
        self.assertEqual(word_frequency("Straße STRASSE"), {"strasse": 2})

    def test_multiple_spaces_are_collapsed(self) -> None:
        """Runs of whitespace between words act as a single separator."""
        self.assertEqual(word_frequency("a  b   a"), {"a": 2, "b": 1})


if __name__ == "__main__":
    unittest.main()
