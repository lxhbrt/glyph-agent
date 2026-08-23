# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import tasks


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = tasks.STORE_PATH
        tasks.STORE_PATH = os.path.join(self.tmp.name, "tasks.json")

    def tearDown(self):
        tasks.STORE_PATH = self.old_path
        self.tmp.cleanup()

    def test_handoff_keeps_selected_evidence_and_build_prompt(self):
        item = tasks.create_item({
            "title": "Composer sendet nicht",
            "source": "glyph-agent",
            "target": "grok",
            "summary": "Bitte Ursache analysieren.",
            "pass": "Ursache steht in einer Datei oder einem reproduzierbaren Schritt",
            "evidence": {"prompt": "Enter sendet nicht", "answer": "Reproduktion offen"},
        })
        self.assertEqual(tasks.list_items()[0]["title"], "Composer sendet nicht")
        prompt = tasks.handoff_prompt(item["id"])
        self.assertIn("Enter sendet nicht", prompt)
        self.assertIn("Bitte Ursache analysieren", prompt)
        self.assertIn("Zielkopf: grok", prompt)
        self.assertIn("Fertig wenn:", prompt)

    def test_create_requires_pass(self):
        with self.assertRaisesRegex(ValueError, "Fertig-Kriterium"):
            tasks.create_item({"title": "Composer"})

    def test_target_is_optional_and_unknown_heads_are_dropped(self):
        item = tasks.create_item({"title": "Composer", "target": "", "pass": "Composer sendet"})
        self.assertEqual(item["target"], "")
        unknown = tasks.create_item({"title": "Alt", "target": "analysis", "pass": "Alt geklärt"})
        self.assertEqual(unknown["target"], "")
        self.assertNotIn("analysis", tasks.HEADS)
        prompt = tasks.handoff_prompt(item["id"])
        self.assertIn("noch nicht zugewiesen", prompt)

    def test_analysis_remains_a_status_not_a_head(self):
        item = tasks.create_item({"title": "Bug", "status": "analysis", "pass": "Ursache benannt"})
        self.assertEqual(item["status"], "analysis")
        self.assertEqual(item["target"], "")

    def test_evidence_keeps_paths_not_blobs(self):
        item = tasks.create_item({
            "title": "Mit Anhang",
            "pass": "Anhang-Pfad bleibt",
            "evidence": {
                "trace": {"model": "deepseek-v4", "blob": "x" * 50, "steps": ["a", "b"]},
                "attachments": [{
                    "name": "a.png",
                    "path": "/tmp/a.png",
                    "content": "AAAA",
                    "previewUrl": "data:image/png;base64,xxxx",
                }],
            },
        })
        att = item["evidence"]["attachments"][0]
        self.assertEqual(att["name"], "a.png")
        self.assertEqual(att["path"], "/tmp/a.png")
        self.assertNotIn("content", att)
        self.assertNotIn("previewUrl", att)
        self.assertEqual(item["evidence"]["trace"]["model"], "deepseek-v4")
        self.assertNotIn("blob", item["evidence"]["trace"])

    def test_status_update_adds_event(self):
        item = tasks.create_item({"title": "Bug", "pass": "Repro steht"})
        updated = tasks.update_item(item["id"], {"status": "ready_to_build", "by": "glyph-agent"})
        self.assertEqual(updated["status"], "ready_to_build")
        self.assertEqual(updated["events"][-1]["type"], "status")

    def test_done_requires_artifact(self):
        item = tasks.create_item({"title": "Bug", "pass": "Fix in Datei"})
        with self.assertRaisesRegex(ValueError, "Artefakt"):
            tasks.update_item(item["id"], {"status": "done"})
        done = tasks.update_item(item["id"], {"status": "done", "artifact": "client/src/App.jsx"})
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["artifact"], "client/src/App.jsx")

    def test_old_items_without_pass_still_load(self):
        data = {
            "version": 1,
            "items": [{"id": "old1", "title": "Alt", "status": "new", "target": "", "source": "grok"}],
        }
        with open(tasks.STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
        loaded = tasks.get_item("old1")
        self.assertEqual(loaded["title"], "Alt")
        self.assertEqual(loaded["pass"], "")


if __name__ == "__main__":
    unittest.main()
