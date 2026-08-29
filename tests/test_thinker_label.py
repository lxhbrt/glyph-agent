#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Think-Step-Label: Direct Pro / OpenRouter Flash — nie flash-0731 → free."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import llm


class ThinkerLabelTests(unittest.TestCase):
    def test_short_labels(self):
        self.assertEqual(llm.short_model_label("deepseek-v4-pro"), "DeepSeek v4 pro")
        self.assertEqual(
            llm.short_model_label("deepseek-v4-flash-vision-exp"),
            "DeepSeek v4 vision",
        )
        self.assertEqual(llm.short_model_label("deepseek-v4-flash"), "DeepSeek v4 flash")
        self.assertEqual(
            llm.short_model_label("deepseek/deepseek-v4-flash-0731"),
            "OpenRouter v4 flash",
        )
        self.assertEqual(llm.short_model_label(""), "?")
        self.assertEqual(
            llm.short_model_label("google/gemini-3.7-flash"),
            "Gemini 3.7 flash",
        )

    def test_agent_detail_uses_primary(self):
        detail = llm.thinker_step_detail("agent", model="deepseek-v4-pro")
        self.assertEqual(detail, "Cloud-Denker denkt (DeepSeek v4 pro)")
        self.assertNotIn("free", detail)
        self.assertNotIn("0731 →", detail)

    def test_agent_fallback_label(self):
        detail = llm.thinker_step_detail(
            "agent", model="deepseek/deepseek-v4-flash-0731"
        )
        self.assertEqual(detail, "Cloud-Denker denkt (OpenRouter v4 flash)")

    def test_code_detail(self):
        detail = llm.thinker_step_detail("code", model="deepseek-v4-flash")
        self.assertEqual(detail, "^_Code denkt (DeepSeek v4 flash)")

    def test_code_gemini_detail(self):
        detail = llm.thinker_step_detail("code", model="google/gemini-3.7-flash")
        self.assertEqual(detail, "^_Code denkt (Gemini 3.7 flash)")
        self.assertNotIn("DeepSeek", detail)


if __name__ == "__main__":
    unittest.main()
