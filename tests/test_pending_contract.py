#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pending-contract.md: eine Nicht-Vault-Datei, die den Chat überlebt."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import vault_tools


class PendingContractTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="glyph-pending-")
        self.path = os.path.join(self._td.name, "pending-contract.md")
        self._old = os.environ.get("GLYPH_PENDING_CONTRACT")
        os.environ["GLYPH_PENDING_CONTRACT"] = self.path

    def tearDown(self):
        if self._old is None:
            os.environ.pop("GLYPH_PENDING_CONTRACT", None)
        else:
            os.environ["GLYPH_PENDING_CONTRACT"] = self._old
        self._td.cleanup()

    def test_resolve_alias(self):
        self.assertEqual(
            vault_tools._resolve_vault_path("pending-contract.md"),
            os.path.abspath(self.path),
        )

    def test_prompt_block_empty_without_items(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("# Offene Vertragsvorschläge\n\nFormat only.\n")
        self.assertIsNone(vault_tools.pending_contract_prompt_block())

    def test_prompt_block_with_item(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(
                "# Offene\n\n"
                "- 2026-08-13 · ~/.glyph/AGENTS.md · Vertrag gewinnt · grok\n"
            )
        block = vault_tools.pending_contract_prompt_block()
        self.assertIsNotNone(block)
        self.assertIn("Vertrag gewinnt", block)

    def test_create_and_read(self):
        body = "# Offene\n\n- 2026-08-13 · MEMORY.md · Lektion X · glyph-agent\n"
        res = vault_tools.create_note(self.path, body)
        self.assertTrue(res["created"])
        note = vault_tools.read_note("pending-contract.md")
        self.assertIn("Lektion X", note["content"])
        self.assertEqual(note["path"], "~/.glyph/memory/pending-contract.md")


if __name__ == "__main__":
    unittest.main()
