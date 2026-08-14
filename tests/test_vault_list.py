#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests: ListVaultDir + verbesserte Keyword-Suche (Dateiname/Tokens).

Kein Netzwerk, kein Ollama. Nutzt echte Vault-Pfade aus config, falls vorhanden;
sonst temporären Mini-Vault.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import vault_tools, tool_registry, tool_loop, config


class TokenizeAndSearchTests(unittest.TestCase):
    def test_tokenize_keeps_date_drops_stopwords(self):
        toks = vault_tools._tokenize_query(
            "Im eingang sollten weitere dateien liegen wie z.b. 2026-06-29"
        )
        self.assertIn("2026-06-29", toks)
        self.assertIn("eingang", toks)
        self.assertNotIn("sollten", toks)
        self.assertNotIn("wie", toks)

    def test_search_vault_hits_filename_date(self):
        """Datum nur im Dateinamen muss Treffer erzeugen (Kernbug)."""
        with tempfile.TemporaryDirectory(prefix="glyph-vault-") as td:
            eingang = os.path.join(td, "00 Arbeitsfluss", "Eingang")
            os.makedirs(eingang)
            path = os.path.join(eingang, "2026-06-29 Internes Audit Rosier.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("# Audit\nInhalt ohne Datumsstring, nur Rosier Sylt.\n")
            old = list(config.VAULT_PATHS)
            try:
                config.VAULT_PATHS = [td]
                config.VAULT_PATH = td
                hits = vault_tools.search_vault("2026-06-29", limit=10)
                paths = [h["path"] for h in hits]
                self.assertTrue(
                    any("2026-06-29" in p for p in paths),
                    f"Dateiname nicht gefunden: {paths}",
                )
                # Natürliche Frage (früher 0 Treffer durch Fullstring-Match)
                hits2 = vault_tools.search_vault(
                    "Im eingang sollten weitere dateien liegen wie z.b. 2026-06-29",
                    limit=10,
                )
                paths2 = [h["path"] for h in hits2]
                self.assertTrue(
                    any("2026-06-29" in p for p in paths2),
                    f"Token-Suche fehlgeschlagen: {paths2}",
                )
            finally:
                config.VAULT_PATHS = old
                config.VAULT_PATH = old[0] if old else td


class ListVaultDirTests(unittest.TestCase):
    def test_list_vault_dir_entries(self):
        with tempfile.TemporaryDirectory(prefix="glyph-vault-") as td:
            eingang = os.path.join(td, "00 Arbeitsfluss", "Eingang")
            os.makedirs(eingang)
            for name in (
                "2026-06-29 Internes Audit Rosier.md",
                "2026-07-15 Umweltschutz Senger.md",
                "README.md",
            ):
                with open(os.path.join(eingang, name), "w", encoding="utf-8") as f:
                    f.write("x\n")
            old = list(config.VAULT_PATHS)
            try:
                config.VAULT_PATHS = [td]
                config.VAULT_PATH = td
                res = vault_tools.list_vault_dir("00 Arbeitsfluss/Eingang")
                self.assertEqual(res["status"], "success", res)
                names = {e["name"] for e in res["entries"]}
                self.assertIn("2026-06-29 Internes Audit Rosier.md", names)
                self.assertIn("2026-07-15 Umweltschutz Senger.md", names)
                self.assertGreaterEqual(res["count"], 3)
            finally:
                config.VAULT_PATHS = old
                config.VAULT_PATH = old[0] if old else td

    def test_list_vault_dir_blocked_and_outside(self):
        with tempfile.TemporaryDirectory(prefix="glyph-vault-") as td:
            old = list(config.VAULT_PATHS)
            try:
                config.VAULT_PATHS = [td]
                config.VAULT_PATH = td
                res = vault_tools.list_vault_dir("/tmp")
                self.assertEqual(res["status"], "error")
                self.assertEqual(res["count"], 0)
            finally:
                config.VAULT_PATHS = old
                config.VAULT_PATH = old[0] if old else td

    def test_registry_and_execute(self):
        names = {t["name"] for t in tool_registry.TOOLS}
        self.assertIn("ListVaultDir", names)
        self.assertFalse(tool_registry.TOOL_MAP["ListVaultDir"]["write"])
        with tempfile.TemporaryDirectory(prefix="glyph-vault-") as td:
            os.makedirs(os.path.join(td, "sub"))
            with open(os.path.join(td, "sub", "a.md"), "w", encoding="utf-8") as f:
                f.write("hi")
            old = list(config.VAULT_PATHS)
            try:
                config.VAULT_PATHS = [td]
                config.VAULT_PATH = td
                out = tool_registry.execute(
                    "ListVaultDir", {"path": "sub"}, mode="agent"
                )
                self.assertTrue(out["ok"], out)
                self.assertEqual(out["result"]["status"], "success")
                self.assertGreaterEqual(out["result"]["count"], 1)
            finally:
                config.VAULT_PATHS = old
                config.VAULT_PATH = old[0] if old else td


class ListQuestionRoutingTests(unittest.TestCase):
    def test_is_list_question_and_path(self):
        self.assertTrue(tool_loop._is_vault_list_question(
            "Welche dokkumente liegen bei mir in Obsidian Ordner sync im eingang?"
        ))
        self.assertTrue(tool_loop._is_vault_list_question(
            "Im eingang sollten weitere dateien liegen wie z.b. 2026-06-29"
        ))
        self.assertFalse(tool_loop._is_vault_list_question(
            "Was ist der Unterschied zwischen Arbeitsschutz und Arbeitssicherheit?"
        ))
        self.assertEqual(
            tool_loop._infer_vault_list_path("was liegt im Eingang?"),
            "00 Arbeitsfluss/Eingang",
        )
        self.assertEqual(
            tool_loop._infer_vault_list_path("Zeig Fertig-Ordner"),
            "00 Arbeitsfluss/Fertig",
        )


class RankingPrefersLiveOverArchive(unittest.TestCase):
    """Primär-Vault / Arbeitsfluss vor Wiki-sources/unsafe-local-Hash-Kopien."""

    def test_live_beats_unsafe_local_slug(self):
        with tempfile.TemporaryDirectory(prefix="glyph-rank-") as td:
            hseq = os.path.join(td, "HSEQ Sync")
            wiki = os.path.join(td, "OpenClaw memory-wiki")
            eingang = os.path.join(hseq, "00 Arbeitsfluss", "Eingang")
            sources = os.path.join(wiki, "sources")
            os.makedirs(eingang)
            os.makedirs(sources)
            live = "2026-08-01 Internes Audit Live.md"
            with open(os.path.join(eingang, live), "w", encoding="utf-8") as f:
                f.write("# Live\nKurzer Inhalt ohne Spam.\n")
            # Lange Archiv-Kopie mit gleichem Datum + Hash-Slug (früher #1)
            arch = (
                "unsafe-local-00-arbeitsfluss-70dc75d2-2026-08-01-"
                "internes-audit-live-md-d1978aae.md"
            )
            with open(os.path.join(sources, arch), "w", encoding="utf-8") as f:
                f.write("# Kopie\n" + ("2026-08-01 " * 40) + "\n")
            old = list(config.VAULT_PATHS)
            try:
                config.VAULT_PATHS = [hseq, wiki]
                config.VAULT_PATH = hseq
                hits = vault_tools.search_vault("2026-08-01", limit=10)
                self.assertTrue(hits, "keine Treffer")
                top = hits[0]
                self.assertEqual(top["vault"], "HSEQ Sync", hits)
                self.assertIn("Eingang", top["path"], hits)
                self.assertNotIn("unsafe-local", top["path"].lower(), hits)
                # Natürliche Inventar-Frage
                hits2 = vault_tools.search_vault(
                    "welche dateien liegen im eingang 2026-08-01", limit=5
                )
                self.assertTrue(hits2)
                self.assertIn("Eingang", hits2[0]["path"], hits2)
            finally:
                config.VAULT_PATHS = old
                config.VAULT_PATH = old[0] if old else hseq


class VaultPrefixPathResolve(unittest.TestCase):
    """ReadNote mit Vault-Präfix 'HSEQ Sync/…' muss greifen (Job-Pfade)."""

    def test_prefix_resolve_live_if_present(self):
        from core import vault_tools, config

        roots = getattr(config, "VAULT_PATHS", [])
        if not roots:
            self.skipTest("keine VAULT_PATHS")
        hseq = None
        for r in roots:
            if "HSEQ Sync" in r and os.path.isdir(r):
                hseq = r
                break
        if not hseq:
            self.skipTest("HSEQ Sync nicht konfiguriert")
        # relativ ohne Präfix
        a = vault_tools.read_note("00 Arbeitsfluss/Eingang/README.md")
        self.assertTrue(a.get("content") is not None or a.get("chars", 0) >= 0)
        # mit Vault-Präfix (früher: Notiz nicht gefunden)
        b = vault_tools.read_note("HSEQ Sync/00 Arbeitsfluss/Eingang/README.md")
        self.assertEqual(a.get("chars"), b.get("chars"))


class LiveEingangSmoke(unittest.TestCase):
    """Optional: echter HSEQ-Vault — dynamisch, keine hardcodierte Datumsnummer."""

    def test_live_eingang_prefers_current_files(self):
        hseq = None
        for p in getattr(config, "VAULT_PATHS", []):
            if os.path.basename(os.path.realpath(p)) == "HSEQ Sync":
                hseq = p
                break
        if not hseq or not os.path.isdir(hseq):
            self.skipTest("HSEQ Sync Vault nicht konfiguriert")
        res = vault_tools.list_vault_dir("00 Arbeitsfluss/Eingang")
        self.assertEqual(res["status"], "success", res)
        entries = [e for e in (res.get("entries") or []) if e.get("type") == "file"]
        md = [e for e in entries if (e.get("name") or "").endswith(".md")
              and (e.get("name") or "").lower() != "readme.md"]
        self.assertTrue(md, f"Eingang ohne Arbeitsdateien: {entries}")
        # Datumstoken aus *aktueller* Datei, nicht hardcodiert
        import re
        date_tok = None
        sample_name = md[0]["name"]
        m = re.search(r"\d{4}-\d{2}-\d{2}", sample_name)
        if m:
            date_tok = m.group(0)
        hits = vault_tools.search_vault(
            date_tok or sample_name.split()[0], limit=15
        )
        paths = [h["path"] for h in hits]
        vaults = [h.get("vault") for h in hits]
        # Top-Treffer: HSEQ Sync, kein unsafe-local-Archiv
        self.assertTrue(hits, "Suche leer")
        self.assertEqual(hits[0].get("vault"), "HSEQ Sync", list(zip(vaults, paths)))
        self.assertFalse(
            any("unsafe-local" in (p or "").lower() for p in paths[:3]),
            f"Archiv-Kopien in Top-3: {paths[:3]}",
        )
        # Mindestens ein Treffer im Arbeitsfluss (Eingang oder Fertig)
        self.assertTrue(
            any(
                "00 Arbeitsfluss" in (h.get("path") or "")
                and h.get("vault") == "HSEQ Sync"
                for h in hits
            ),
            f"Kein HSEQ-Arbeitsfluss-Treffer: {paths}",
        )


if __name__ == "__main__":
    unittest.main()
