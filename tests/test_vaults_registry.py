# -*- coding: utf-8 -*-
"""Vaults Kabelsalat: attach / mode / primary / enabled / exists-Projektion."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from core import bind_store, config


class VaultsRegistryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.store = os.path.join(self.root, "vaults.json")
        self.va = os.path.realpath(os.path.join(self.root, "vault-a"))
        self.vb = os.path.realpath(os.path.join(self.root, "vault-b"))
        os.makedirs(self.va)
        os.makedirs(self.vb)

        import core.vaults_registry as vr

        self.vr = vr
        self._orig_dir = vr.GLYPH_DIR
        self._orig_store = vr.USER_STORE
        self._orig_defaults = vr.DEFAULTS_STORE
        self._old_paths = list(config.VAULT_PATHS)
        self._old_path = config.VAULT_PATH
        vr.GLYPH_DIR = self.root
        vr.USER_STORE = self.store
        vr.DEFAULTS_STORE = os.path.join(self.root, "vaults.defaults.json")
        bind_store._mtime_cache.clear()
        with open(self.store, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "vaults": []}, f)

    def tearDown(self):
        self.vr.GLYPH_DIR = self._orig_dir
        self.vr.USER_STORE = self._orig_store
        self.vr.DEFAULTS_STORE = self._orig_defaults
        config.VAULT_PATHS = self._old_paths
        config.VAULT_PATH = self._old_path
        bind_store._mtime_cache.clear()
        self._tmp.cleanup()

    def test_attach_duplicate_missing(self):
        vr = self.vr
        res = vr.attach(self.va, mode="r")
        self.assertTrue(res["vault"]["exists"])
        self.assertEqual(res["vault"]["mode"], "r")
        self.assertTrue(res["vault"]["primary"])
        self.assertTrue(res["vault"]["enabled"])

        with self.assertRaises(ValueError):
            vr.attach(self.va, mode="rw")
        with self.assertRaises(ValueError):
            vr.attach(os.path.join(self.root, "nope"), mode="r")

    def test_mode_cycle_including_r_plus_w(self):
        vr = self.vr
        res = vr.attach(self.va, mode="r+w")
        self.assertEqual(res["vault"]["mode"], "rw")
        vid = res["vault"]["id"]

        updated = vr.update_vault(vid, {"mode": "private"})
        self.assertEqual(updated["mode"], "private")
        updated = vr.update_vault(vid, {"mode": "r"})
        self.assertEqual(updated["mode"], "r")
        updated = vr.update_vault(vid, {"mode": "r+w"})
        self.assertEqual(updated["mode"], "rw")

    def test_primary_reorder(self):
        vr = self.vr
        a = vr.attach(self.va, mode="r")["vault"]
        b = vr.attach(self.vb, mode="r")["vault"]
        self.assertTrue(a["primary"])
        self.assertFalse(b["primary"])

        vr.update_vault(b["id"], {"primary": True})
        snap = vr.list_vaults()
        self.assertEqual(snap[0]["id"], b["id"])
        self.assertTrue(snap[0]["primary"])
        self.assertFalse(any(v["primary"] and v["id"] == a["id"] for v in snap))

    def test_enabled_and_private_filter(self):
        vr = self.vr
        a = vr.attach(self.va, mode="rw")["vault"]
        b = vr.attach(self.vb, mode="private")["vault"]
        self.assertIn(self.va, vr.paths_for_agent())
        self.assertIn(self.vb, vr.paths_for_agent())
        self.assertIn(self.vb, vr.private_paths())
        self.assertIn(self.va, vr.writable_paths())
        self.assertNotIn(self.vb, vr.writable_paths())

        vr.update_vault(a["id"], {"enabled": False})
        self.assertNotIn(self.va, vr.paths_for_agent())
        self.assertIn(self.vb, vr.paths_for_agent())

        vr.update_vault(b["id"], {"enabled": False})
        self.assertEqual(vr.paths_for_agent(), [])
        self.assertEqual(vr.private_paths(), [])

    def test_save_disk_has_no_exists_load_old_exists(self):
        vr = self.vr
        vr.attach(self.va, mode="r")
        with open(self.store, encoding="utf-8") as f:
            disk = json.load(f)
        self.assertTrue(disk["vaults"])
        for item in disk["vaults"]:
            self.assertNotIn("exists", item)
            self.assertIn("id", item)
            self.assertIn("path", item)
            self.assertIn("mode", item)

        # Altbestand mit exists bleibt lesbar; live exists überschreibt
        disk["vaults"][0]["exists"] = False
        with open(self.store, "w", encoding="utf-8") as f:
            json.dump(disk, f)
        bind_store._mtime_cache.clear()
        loaded = vr.load_store(force=True)
        self.assertTrue(loaded["vaults"][0]["exists"])

    def test_cache_after_save_has_live_exists(self):
        vr = self.vr
        vr.attach(self.va, mode="r")
        cached = vr.load_store()  # ohne force
        self.assertTrue(cached["vaults"])
        for item in cached["vaults"]:
            self.assertIn("exists", item)
            self.assertEqual(item["exists"], os.path.isdir(item["path"]))

    def test_update_vault_pins_after_update_item(self):
        vr = self.vr
        vid = vr.attach(self.va, mode="r")["vault"]["id"]
        updated = vr.update_vault(
            vid,
            {
                "pins": [
                    {"path": "note.md", "label": "N"},
                    {"path": "note.md"},
                    "bad",
                    {"path": ""},
                ],
                "bogus": True,
            },
        )
        paths = [p["path"] for p in updated.get("pins") or []]
        self.assertEqual(paths, ["note.md"])
        self.assertNotIn("bogus", updated)


if __name__ == "__main__":
    unittest.main()
