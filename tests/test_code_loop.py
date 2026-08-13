# -*- coding: utf-8 -*-
"""Unit tests for ^_Code loop policy (trim, Orient, retry, Grep-x3)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import code_loop, config


class TrimHistoryTests(unittest.TestCase):
    def test_keeps_first_user_and_last_tool(self):
        hist = [
            {"role": "user", "content": "TASK " + ("x" * 100)},
            {"role": "assistant", "content": "grep1"},
            {"role": "user", "content": "OLD RESULT " + ("y" * 400)},
            {"role": "assistant", "content": "grep2"},
            {"role": "user", "content": "LATEST TOOL RESULT unique-tail"},
        ]
        kept = code_loop.trim_code_history(hist, budget=250)
        self.assertEqual(kept[0]["content"][:4], "TASK")
        self.assertIn("unique-tail", kept[-1]["content"])
        self.assertLess(len(kept), len(hist))

    def test_under_budget_unchanged(self):
        hist = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]
        self.assertEqual(code_loop.trim_code_history(hist, 1000), hist)


class OrientExtractTests(unittest.TestCase):
    def test_orient_and_map_only(self):
        md = (
            "# Repo\n\n"
            "## Orient\n1. Read this.\n\n"
            "## System map\n| Node | Tut |\n\n"
            "## Language\nComposer: input\n"
        )
        got = code_loop.extract_orient_map(md)
        self.assertIn("## Orient", got)
        self.assertIn("## System map", got)
        self.assertNotIn("## Language", got)
        self.assertNotIn("Composer:", got)

    def test_real_glyph_agent_context(self):
        path = os.path.join(os.path.dirname(__file__), "..", "CONTEXT.md")
        with open(path, encoding="utf-8") as f:
            got = code_loop.extract_orient_map(f.read())
        self.assertIn("## Orient", got)
        self.assertIn("## System map", got)
        self.assertNotIn("## Language", got)
        self.assertNotIn("Settled decisions", got)


class RetryAndHardStopTests(unittest.TestCase):
    def test_search_replace_miss_is_retryable(self):
        r = {"ok": False, "error": "SearchReplace: old-String nicht gefunden (0 Treffer)"}
        self.assertTrue(code_loop.is_retryable_write_fail("SearchReplace", r))
        self.assertFalse(code_loop.should_hard_stop("SearchReplace", r))

    def test_search_replace_n_hits_retryable(self):
        r = {"ok": False, "error": "SearchReplace: old-String kommt 3× vor — muss exakt 1 Treffer sein"}
        self.assertTrue(code_loop.is_retryable_write_fail("SearchReplace", r))
        self.assertFalse(code_loop.should_hard_stop("SearchReplace", r))

    def test_user_deny_hard(self):
        r = {"ok": False, "error": "Vom Nutzer in Glyph abgelehnt."}
        self.assertTrue(code_loop.should_hard_stop("RunCommand", r))

    def test_shell_timeout_hard(self):
        r = {"ok": True, "result": {"timeout": True, "exit_code": -1}}
        self.assertTrue(code_loop.should_hard_stop("RunCommand", r))

    def test_private_hard(self):
        r = {"ok": False, "error": "Schreiben verboten: Mode private (braucht r+w)"}
        self.assertTrue(code_loop.should_hard_stop("WriteFile", r))


class RepeatKeyTests(unittest.TestCase):
    def test_same_grep_same_key(self):
        a = code_loop.repeat_tool_key("Grep", {"pattern": "foo", "path": "."})
        b = code_loop.repeat_tool_key("Grep", {"pattern": "foo", "path": "."})
        c = code_loop.repeat_tool_key("Grep", {"pattern": "bar", "path": "."})
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_write_not_tracked(self):
        self.assertIsNone(code_loop.repeat_tool_key("WriteFile", {"path": "a.py"}))


class PickTestTests(unittest.TestCase):
    def test_package_json_npm(self):
        d = tempfile.TemporaryDirectory()
        try:
            with open(os.path.join(d.name, "package.json"), "w") as fh:
                fh.write("{}")
            self.assertEqual(code_loop.pick_test_command(d.name), "npm test")
        finally:
            d.cleanup()

    def test_tests_dir_pytest(self):
        d = tempfile.TemporaryDirectory()
        try:
            os.mkdir(os.path.join(d.name, "tests"))
            self.assertEqual(code_loop.pick_test_command(d.name), "pytest")
        finally:
            d.cleanup()

    def test_empty_none(self):
        d = tempfile.TemporaryDirectory()
        try:
            self.assertIsNone(code_loop.pick_test_command(d.name))
        finally:
            d.cleanup()


class ConfigRoundsTests(unittest.TestCase):
    def test_default_at_least_32(self):
        self.assertGreaterEqual(int(config.CODE_MAX_ROUNDS), 32)
        self.assertGreaterEqual(int(getattr(config, "CODE_MESSAGE_CHARS", 0)), 64000)


if __name__ == "__main__":
    unittest.main()
