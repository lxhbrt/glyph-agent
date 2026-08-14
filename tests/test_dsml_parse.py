# -*- coding: utf-8 -*-
"""DSML-Tool-Call-Parser (DeepSeek V4 Leak als Text)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import tool_registry as tr


# Screenshot-Fall: ASCII-||, kompakt, Grep pattern + max_hits
_SCREENSHOT = (
    '<||DSML||tool_calls>'
    '<||DSML||invoke name="Grep">'
    '<||DSML||parameter name="pattern" string="true">'
    'Cloud-Denker|deepseek-v4-flash-0731'
    '</||DSML||parameter>'
    '<||DSML||parameter name="max_hits" string="false">50</||DSML||parameter>'
    '</||DSML||invoke>'
    '</||DSML||tool_calls>'
)

_FULLWIDTH = (
    "<\uff5cDSML\uff5ctool_calls>\n"
    '<\uff5cDSML\uff5cinvoke name="ReadFile">\n'
    '<\uff5cDSML\uff5cparameter name="path" string="true">CONTEXT.md</\uff5cDSML\uff5cparameter>\n'
    '<\uff5cDSML\uff5cparameter name="limit" string="false">80</\uff5cDSML\uff5cparameter>\n'
    "</\uff5cDSML\uff5cinvoke>\n"
    "</\uff5cDSML\uff5ctool_calls>"
)

_SPACED = (
    "< | | DSML | | tool_calls>"
    '< | | DSML | | invoke name="Grep">'
    '< | | DSML | | parameter name="pattern" string="true">'
    "foo"
    "< | | DSML | | parameter>"
    "</ | | DSML | | invoke>"
    "</ | | DSML | | tool_calls>"
)


class DsmlParseTests(unittest.TestCase):
    def test_screenshot_double_pipe(self):
        r = tr.try_parse_tool_call(_SCREENSHOT)
        self.assertIsNotNone(r)
        name, args = r
        self.assertEqual(name, "Grep")
        self.assertEqual(args["pattern"], "Cloud-Denker|deepseek-v4-flash-0731")
        self.assertEqual(args["max_hits"], 50)
        self.assertIsInstance(args["max_hits"], int)

    def test_fullwidth_token(self):
        r = tr.try_parse_tool_call(_FULLWIDTH)
        self.assertIsNotNone(r)
        name, args = r
        self.assertEqual(name, "ReadFile")
        self.assertEqual(args["path"], "CONTEXT.md")
        self.assertEqual(args["limit"], 80)

    def test_markdown_spaced_pipes(self):
        r = tr.try_parse_tool_call(_SPACED)
        self.assertIsNotNone(r)
        name, args = r
        self.assertEqual(name, "Grep")
        self.assertEqual(args["pattern"], "foo")

    def test_single_pipe_variant(self):
        raw = (
            '<|DSML|tool_calls><|DSML|invoke name="ListDir">'
            '<|DSML|parameter name="path" string="true">.</|DSML|parameter>'
            "</|DSML|invoke></|DSML|tool_calls>"
        )
        r = tr.try_parse_tool_call(raw)
        self.assertEqual(r[0], "ListDir")
        self.assertEqual(r[1]["path"], ".")

    def test_prose_then_dsml(self):
        raw = "Ich suche zuerst.\n" + _SCREENSHOT
        r = tr.try_parse_tool_call(raw)
        self.assertEqual(r[0], "Grep")
        self.assertEqual(tr.prose_before_dsml(raw), "Ich suche zuerst.")

    def test_bool_and_json_nonstring(self):
        raw = (
            '<||DSML||invoke name="ListDir">'
            '<||DSML||parameter name="recursive" string="false">true</||DSML||parameter>'
            "</||DSML||invoke>"
        )
        r = tr.try_parse_tool_call(raw)
        self.assertEqual(r[1]["recursive"], True)

    def test_json_still_works(self):
        r = tr.try_parse_tool_call('{"tool":"WebSearch","args":{"query":"x"}}')
        self.assertEqual(r[0], "WebSearch")
        self.assertEqual(r[1]["query"], "x")

    def test_plain_text_none(self):
        self.assertIsNone(tr.try_parse_tool_call("Hallo, keine Lust?"))
        self.assertFalse(tr.looks_like_dsml("Hallo, keine Lust?"))

    def test_looks_like_dsml(self):
        self.assertTrue(tr.looks_like_dsml(_SCREENSHOT))
        self.assertTrue(tr.looks_like_dsml(_FULLWIDTH))

    def test_native_parameter_close_without_slash(self):
        """Live-Leak: Parameter endet mit <||DSML||parameter>, nicht </…>."""
        raw = (
            '<||DSML||tool_calls>'
            '<||DSML||invoke name="Grep">'
            '<||DSML||parameter name="pattern" string="true">'
            "Cloud-Denker|deepseek-v4-flash-0731"
            "<||DSML||parameter>"
            '<||DSML||parameter name="max_hits" string="false">50'
            "<||DSML||parameter>"
            "</||DSML||invoke>"
            "</||DSML||tool_calls>"
        )
        r = tr.try_parse_tool_call(raw)
        self.assertIsNotNone(r)
        name, args = r
        self.assertEqual(name, "Grep")
        self.assertEqual(args["pattern"], "Cloud-Denker|deepseek-v4-flash-0731")
        self.assertEqual(args["max_hits"], 50)


if __name__ == "__main__":
    unittest.main()
