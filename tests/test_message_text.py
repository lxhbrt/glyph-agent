#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenRouter _message_text: Gemini reasoning / native tool_calls."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.providers.openrouter import _message_text


class MessageTextTests(unittest.TestCase):
    def test_plain_content(self):
        data = {"choices": [{"message": {"content": "Hallo"}}]}
        self.assertEqual(_message_text(data), "Hallo")

    def test_gemini_reasoning_field(self):
        data = {
            "choices": [{
                "message": {
                    "content": "",
                    "reasoning": '{"tool": "ReadFile", "args": {"path": "CONTEXT.md"}}',
                }
            }]
        }
        text = _message_text(data)
        self.assertIn("ReadFile", text)
        self.assertIn("CONTEXT.md", text)

    def test_gemini_content_parts_reasoning(self):
        data = {
            "choices": [{
                "message": {
                    "content": [
                        {"type": "reasoning", "reasoning": '{"tool": "Grep", "args": {"pattern": "x"}}'},
                        {"type": "text", "text": ""},
                    ]
                }
            }]
        }
        self.assertIn("Grep", _message_text(data))

    def test_native_tool_calls(self):
        data = {
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "function": {
                            "name": "WriteFile",
                            "arguments": json.dumps({"path": "a.py", "content": "x"}),
                        }
                    }],
                }
            }]
        }
        text = _message_text(data)
        obj = json.loads(text)
        self.assertEqual(obj["tool"], "WriteFile")
        self.assertEqual(obj["args"]["path"], "a.py")

    def test_empty(self):
        self.assertEqual(_message_text({"choices": [{"message": {"content": ""}}]}), "")
        self.assertEqual(_message_text({}), "")

    def test_skips_encrypted_reasoning_details(self):
        data = {
            "choices": [{
                "message": {
                    "content": "",
                    "reasoning_details": [
                        {"type": "reasoning.encrypted", "data": "abcd"},
                    ],
                }
            }]
        }
        self.assertEqual(_message_text(data), "")


if __name__ == "__main__":
    unittest.main()
