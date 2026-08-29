# -*- coding: utf-8 -*-
"""Lesespur: draft vs answer — Zwischen-LLM nie als answer."""
import unittest

from core.tool_loop import _maybe_emit_tool_reply_draft


class DraftEmitTests(unittest.TestCase):
    def test_pure_tool_json_not_drafted(self):
        events = []
        _maybe_emit_tool_reply_draft(
            events.append,
            '{"tool": "WebSearch", "args": {"query": "helm"}}',
        )
        self.assertEqual(events, [])

    def test_prose_before_tool_is_draft(self):
        events = []
        text = "Ich prüfe die Quellen.\n{\"tool\": \"WebSearch\", \"args\": {\"query\": \"x\"}}"
        _maybe_emit_tool_reply_draft(events.append, text)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "draft")
        self.assertIn("Ich prüfe", events[0]["text"])

    def test_empty_noop(self):
        events = []
        _maybe_emit_tool_reply_draft(events.append, "  ")
        self.assertEqual(events, [])

    def test_pure_dsml_not_drafted(self):
        events = []
        raw = (
            "<\uff5c\uff5cDSML\uff5c\uff5ctool_calls>"
            '<\uff5c\uff5cDSML\uff5c\uff5cinvoke name="VaultFind">'
            '<\uff5c\uff5cDSML\uff5c\uff5cparameter name="query" string="true">Kran'
            "</\uff5c\uff5cDSML\uff5c\uff5cparameter>"
            "</\uff5c\uff5cDSML\uff5c\uff5cinvoke>"
            "</\uff5c\uff5cDSML\uff5c\uff5ctool_calls>"
        )
        _maybe_emit_tool_reply_draft(events.append, raw)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
