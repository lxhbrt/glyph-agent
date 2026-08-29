#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chat-Wachstum: anlegen/ergänzen ja, löschen/leeren/Eingang nein."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import vault_tools, vault_write_policy


NOTE = "# Nomex\n\nMultinorm-Jacke, Hitzeschutz.\n"


class ChatWritePolicyTests(unittest.TestCase):
    def test_create_themen_hub(self):
        self.assertTrue(
            vault_write_policy.allow_chat_write(
                "CreateNote",
                {"path": "Themen/PSA-Multinorm.md", "content": NOTE},
            )
        )
        self.assertTrue(
            vault_write_policy.allow_chat_write(
                "CreateNote",
                {"path": "/HSEQ Sync/Themen/PSA-Multinorm.md", "content": NOTE},
            )
        )

    def test_apply_existing_themen(self):
        self.assertTrue(
            vault_write_policy.allow_chat_write(
                "ApplyEdit",
                {"path": "Themen/PSA.md", "new_content": NOTE + "\n## Nomex\n"},
            )
        )

    def test_wiki_create_and_apply(self):
        self.assertTrue(
            vault_write_policy.allow_chat_write(
                "CreateNote",
                {"path": "memory-wiki/concepts/nomex.md", "content": NOTE},
            )
        )
        self.assertTrue(
            vault_write_policy.allow_chat_write(
                "ApplyEdit",
                {"path": "concepts/nomex.md", "new_content": NOTE},
            )
        )
        self.assertTrue(
            vault_write_policy.allow_chat_write(
                "CreateNote",
                {"path": "sources/2026-08-26--nomex.md", "content": NOTE},
            )
        )

    def test_pending_contract_ok(self):
        self.assertTrue(
            vault_write_policy.allow_chat_write(
                "ApplyEdit",
                {
                    "path": "~/.glyph/memory/pending-contract.md",
                    "new_content": "- 2026-08-26 · Themen/PSA.md · Nomex · glyph-agent\n",
                },
            )
        )

    def test_no_delete_tool(self):
        self.assertFalse(
            vault_write_policy.allow_chat_write(
                "DeleteNote", {"path": "Themen/PSA.md"}
            )
        )
        self.assertFalse(
            vault_write_policy.allow_chat_write("WikiDelete", {"path": "concepts/x.md"})
        )

    def test_empty_content_denied(self):
        self.assertFalse(
            vault_write_policy.allow_chat_write(
                "CreateNote", {"path": "Themen/x.md", "content": "  \n"}
            )
        )
        self.assertFalse(
            vault_write_policy.allow_chat_write(
                "ApplyEdit", {"path": "Themen/PSA.md", "new_content": ""}
            )
        )

    def test_immutable_and_out_of_scope(self):
        self.assertFalse(
            vault_write_policy.allow_chat_write(
                "ApplyEdit",
                {"path": "sources/2026-08-26--nomex.md", "new_content": NOTE},
            )
        )
        self.assertFalse(
            vault_write_policy.allow_chat_write(
                "ApplyEdit",
                {
                    "path": "00 Arbeitsfluss/Eingang/notiz.md",
                    "new_content": NOTE,
                },
            )
        )
        self.assertFalse(
            vault_write_policy.allow_chat_write(
                "CreateNote",
                {"path": "Vorlagen/GBU/neu.md", "content": NOTE},
            )
        )
        self.assertFalse(
            vault_write_policy.allow_chat_write(
                "ApplyEdit",
                {"path": "00 Arbeitsfluss/Fertig/bericht.md", "new_content": NOTE},
            )
        )
        self.assertFalse(
            vault_write_policy.allow_chat_write(
                "CreateNote",
                {"path": "Privat/geheim.md", "content": NOTE},
            )
        )
        self.assertFalse(
            vault_write_policy.allow_chat_write(
                "CreateNote",
                {
                    "path": "ASI, BS. UWS, QM, EM/Arbeitssicherheit/PSA/nomex.md",
                    "content": NOTE,
                },
            )
        )

    def test_chat_confirm_allows_themen(self):
        confirm = vault_write_policy.make_chat_confirm()
        self.assertTrue(
            confirm("CreateNote", {"path": "Themen/PSA-Multinorm.md", "content": NOTE})
        )
        self.assertFalse(
            confirm("CreateNote", {"path": "Vorlagen/x.md", "content": NOTE})
        )


class EmptyWriteGuards(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="glyph-grow-")
        self.path = os.path.join(self._td.name, "pending-contract.md")
        self._old = os.environ.get("GLYPH_PENDING_CONTRACT")
        os.environ["GLYPH_PENDING_CONTRACT"] = self.path
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("# Offene\n\n- bleibt.\n")

    def tearDown(self):
        if self._old is None:
            os.environ.pop("GLYPH_PENDING_CONTRACT", None)
        else:
            os.environ["GLYPH_PENDING_CONTRACT"] = self._old
        self._td.cleanup()

    def test_apply_edit_rejects_empty(self):
        with self.assertRaises(ValueError) as ctx:
            vault_tools.apply_edit("pending-contract.md", "  \n")
        self.assertIn("leeren", str(ctx.exception).lower())

    def test_create_note_rejects_empty(self):
        with self.assertRaises(ValueError) as ctx:
            vault_tools.create_note("pending-contract.md", "   ")
        self.assertIn("leer", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
