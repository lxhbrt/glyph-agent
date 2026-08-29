# -*- coding: utf-8 -*-
"""Grant-Store: Scope, Pfade, ALWAYS_ONCE, Task-Hinweis."""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import code_grants


class CodeGrantsTests(unittest.TestCase):
    def setUp(self):
        code_grants.reset()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)

    def tearDown(self):
        code_grants.reset()
        self._tmp.cleanup()

    def test_path_allowed_prefix_and_glob(self):
        self.assertTrue(code_grants.path_allowed(["client/src"], "client/src/App.jsx"))
        self.assertTrue(code_grants.path_allowed(["client/src/**"], "client/src/a.js"))
        self.assertFalse(code_grants.path_allowed(["client/src"], "server/index.js"))
        self.assertTrue(code_grants.path_allowed(["."], "server/index.js"))

    def test_common_prefixes_shared_dir(self):
        self.assertEqual(
            code_grants.common_prefixes(
                ["client/src/a.js", "client/src/b.css"]
            ),
            ["client/src"],
        )

    def test_common_prefixes_mixed(self):
        got = code_grants.common_prefixes(
            ["client/src/a.js", "server/index.js"]
        )
        self.assertEqual(got, ["client/src", "server"])

    def test_task_covers_file_change_in_prefix(self):
        code_grants.issue(
            "task",
            workspace_root=self.root,
            path_prefixes=["client/src"],
            action_classes=["file_change", "test"],
            label="Dark Mode",
        )
        hit = code_grants.matching(
            self.root, "client/src/App.jsx", "file_change"
        )
        self.assertIsNotNone(hit)
        self.assertEqual(code_grants.why_allowed(hit), "Task Dark Mode")
        miss = code_grants.matching(
            self.root, "server/index.js", "file_change"
        )
        self.assertIsNone(miss)
        hint = code_grants.outside_task_hint(
            self.root, "server/index.js", "file_change"
        )
        self.assertIn("außerhalb", hint)

    def test_always_once_never_matches(self):
        code_grants.issue(
            "task",
            workspace_root=self.root,
            path_prefixes=["."],
            action_classes=["file_change", "package_install"],
            label="X",
        )
        self.assertIsNone(
            code_grants.matching(self.root, "package.json", "package_install")
        )
        hint = code_grants.outside_task_hint(
            self.root, "package.json", "package_install"
        )
        self.assertIn("außerhalb", hint)

    def test_once_consumed_after_match(self):
        code_grants.issue(
            "once",
            workspace_root=self.root,
            path_prefixes=["client"],
            action_classes=["file_change"],
        )
        self.assertIsNotNone(
            code_grants.matching(self.root, "client/a.js", "file_change")
        )
        self.assertIsNone(
            code_grants.matching(self.root, "client/b.js", "file_change")
        )

    def test_auftrag_dies_on_new_run(self):
        aid = code_grants.begin_auftrag()
        code_grants.issue(
            "auftrag",
            workspace_root=self.root,
            path_prefixes=["."],
            action_classes=["file_change"],
            auftrag_id=aid,
        )
        self.assertIsNotNone(
            code_grants.matching(self.root, "a.js", "file_change", auftrag_id=aid)
        )
        code_grants.begin_auftrag()
        self.assertIsNone(
            code_grants.matching(self.root, "a.js", "file_change")
        )

    def test_close_task_stops_match(self):
        code_grants.issue(
            "task",
            workspace_root=self.root,
            path_prefixes=["."],
            action_classes=["file_change"],
            label="T",
        )
        self.assertTrue(code_grants.close_task())
        self.assertIsNone(code_grants.active_task())
        self.assertIsNone(
            code_grants.matching(self.root, "a.js", "file_change")
        )

    def test_task_idle_expires(self):
        g = code_grants.issue(
            "task",
            workspace_root=self.root,
            path_prefixes=["."],
            action_classes=["file_change"],
            label="alt",
        )
        with code_grants._LOCK:
            code_grants._GRANTS[g["grant_id"]]["last_used_at"] = time.time() - (
                code_grants.TASK_IDLE_S + 10
            )
        self.assertIsNone(code_grants.active_task())


if __name__ == "__main__":
    unittest.main()
