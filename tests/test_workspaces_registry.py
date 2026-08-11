# -*- coding: utf-8 -*-
"""Workspaces Kabelsalat (Phase 2): attach / mode / detach."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock


class WorkspacesRegistryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.store = os.path.join(self.root, "workspaces.json")
        self.ws_a = os.path.realpath(os.path.join(self.root, "proj-a"))
        self.ws_b = os.path.realpath(os.path.join(self.root, "proj-b"))
        os.makedirs(self.ws_a)
        os.makedirs(self.ws_b)

        # Isolate registry module paths
        import core.workspaces_registry as wr

        self.wr = wr
        self._orig_dir = wr.GLYPH_DIR
        self._orig_store = wr.USER_STORE
        wr.GLYPH_DIR = self.root
        wr.USER_STORE = self.store
        wr._mtime_cache = (0.0, None)

    def tearDown(self):
        self.wr.GLYPH_DIR = self._orig_dir
        self.wr.USER_STORE = self._orig_store
        self.wr._mtime_cache = (0.0, None)
        self._tmp.cleanup()

    def test_attach_mode_primary_detach(self):
        wr = self.wr
        # empty store first (no seed dirs under tmp)
        with open(self.store, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "workspaces": []}, f)

        res = wr.attach(self.ws_a, mode="rw")
        self.assertTrue(res["workspace"]["exists"])
        self.assertEqual(res["workspace"]["mode"], "rw")
        self.assertTrue(res["workspace"]["primary"])

        res2 = wr.attach(self.ws_b, mode="r")
        self.assertEqual(res2["workspace"]["mode"], "r")
        self.assertFalse(res2["workspace"]["primary"])

        snap = wr.public_snapshot()
        self.assertEqual(len(snap["workspaces"]), 2)
        self.assertIn(self.ws_a, snap["accessible_roots"])

        wid_b = res2["workspace"]["id"]
        updated = wr.update_workspace(wid_b, {"mode": "private", "primary": True})
        self.assertEqual(updated["mode"], "private")
        self.assertTrue(updated["primary"])
        # private not in accessible
        self.assertNotIn(self.ws_b, wr.accessible_roots())

        ok = wr.detach(wid_b)
        self.assertTrue(ok)
        self.assertEqual(len(wr.list_workspaces()), 1)

    def test_attach_duplicate_raises(self):
        wr = self.wr
        with open(self.store, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "workspaces": []}, f)
        wr.attach(self.ws_a, mode="r")
        with self.assertRaises(ValueError):
            wr.attach(self.ws_a, mode="rw")

    def test_attach_missing_raises(self):
        wr = self.wr
        with open(self.store, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "workspaces": []}, f)
        with self.assertRaises(ValueError):
            wr.attach(os.path.join(self.root, "nope"), mode="r")


if __name__ == "__main__":
    unittest.main()
