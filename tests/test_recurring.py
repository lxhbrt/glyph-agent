# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import recurring


class RecurringFinishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_store = recurring.STORE_PATH
        self.old_events = recurring.EVENTS_PATH
        recurring.STORE_PATH = os.path.join(self.tmp.name, "recurring.json")
        recurring.EVENTS_PATH = os.path.join(self.tmp.name, "events.jsonl")

    def tearDown(self):
        recurring.STORE_PATH = self.old_store
        recurring.EVENTS_PATH = self.old_events
        self.tmp.cleanup()

    def test_pass_is_optional_and_preserved(self):
        item = recurring.create_item({
            "title": "Briefing",
            "prompt": "Inbox lesen",
            "schedule": {"kind": "daily", "time": "07:30"},
            "pass": "Ein Slack-Post mit Links, keine Mail gesendet",
        })
        self.assertEqual(item["pass"], "Ein Slack-Post mit Links, keine Mail gesendet")
        loaded = recurring.get_item(item["id"])
        self.assertEqual(loaded["pass"], item["pass"])
        bare = recurring.create_item({
            "title": "Alt",
            "prompt": "HSEQ",
            "schedule": {"kind": "daily", "time": "18:00"},
        })
        self.assertNotIn("pass", bare)

    def test_message_appends_pass_and_leer_rule(self):
        msg = recurring.message_for_run({
            "prompt": "Daily YYYY-MM-DD schreiben",
            "pass": "Daily mit 3-Zeilen-Briefing",
        })
        self.assertIn("Daily ", msg)
        self.assertNotIn("YYYY-MM-DD", msg)
        self.assertIn("Fertig nur wenn: Daily mit 3-Zeilen-Briefing", msg)
        self.assertIn("erste Zeile genau LEER", msg)
        plain = recurring.message_for_run({"prompt": "Nur HSEQ"})
        self.assertEqual(plain, "Nur HSEQ")
        self.assertNotIn("LEER", plain)

    def test_classify_empty_only_with_pass(self):
        self.assertEqual(recurring.classify_run_status(True, "LEER", True), "empty")
        self.assertEqual(recurring.classify_run_status(True, "LEER: nichts", True), "empty")
        self.assertEqual(recurring.classify_run_status(True, "LEER", False), "ok")
        self.assertEqual(recurring.classify_run_status(True, "", True), "error")
        self.assertEqual(recurring.classify_run_status(True, "Daily geschrieben", True), "ok")
        self.assertEqual(recurring.classify_run_status(False, "LEER", True), "error")

    def test_empty_run_stamps_and_is_not_ok(self):
        item = recurring.create_item({
            "title": "Briefing",
            "prompt": "Inbox",
            "schedule": {"kind": "daily", "time": "00:00"},
            "pass": "Ein Post",
        })
        recurring._set_run_result(item["id"], "empty", "LEER", "2026-08-23")
        loaded = recurring.get_item(item["id"])
        self.assertEqual(loaded["last_status"], "empty")
        self.assertEqual(loaded["last_stamp"], "2026-08-23")


if __name__ == "__main__":
    unittest.main()
