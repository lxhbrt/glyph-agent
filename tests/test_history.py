# -*- coding: utf-8 -*-
"""Tests für Multi-Turn-History (core.history)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import history


class TestNormalizePriorHistory(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(history.normalize_prior_history(None), [])
        self.assertEqual(history.normalize_prior_history([]), [])
        self.assertEqual(history.normalize_prior_history("nope"), [])

    def test_keeps_user_assistant(self):
        raw = [
            {"role": "user", "content": "3 Trimmer A B C vergleichen"},
            {"role": "assistant", "content": "A, B und C im Vergleich …"},
            {"role": "system", "content": "ignore"},
            {"role": "user", "content": "Welcher ist der beste?"},
        ]
        got = history.normalize_prior_history(raw)
        self.assertEqual(len(got), 3)
        self.assertEqual(got[0]["role"], "user")
        self.assertEqual(got[1]["role"], "assistant")
        self.assertIn("A, B", got[1]["content"])

    def test_strips_trailing_current_message(self):
        raw = [
            {"role": "user", "content": "Turn 1"},
            {"role": "assistant", "content": "Antwort 1"},
            {"role": "user", "content": "Nach frage"},
        ]
        got = history.normalize_prior_history(raw, current_message="Nach frage")
        self.assertEqual(len(got), 2)
        self.assertEqual(got[-1]["role"], "assistant")

    def test_build_history_for_loop(self):
        prior, full = history.build_history_for_loop(
            "und Erfahrungsberichte?",
            [
                {"role": "user", "content": "3 Trimmer"},
                {"role": "assistant", "content": "Philips, Braun, Wahl"},
                {"role": "user", "content": "und Erfahrungsberichte?"},
            ],
        )
        self.assertEqual(len(prior), 2)
        self.assertEqual(full[-1]["content"], "und Erfahrungsberichte?")
        self.assertEqual(full[-1]["role"], "user")
        self.assertEqual(len(full), 3)

    def test_format_prior_block(self):
        block = history.format_prior_block([
            {"role": "user", "content": "Hallo"},
            {"role": "assistant", "content": "Hi"},
        ])
        self.assertIn("Nutzer", block)
        self.assertIn("Assistent", block)
        self.assertIn("Hallo", block)


if __name__ == "__main__":
    unittest.main()
