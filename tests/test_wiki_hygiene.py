#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wiki-Hygiene: Scan, Digest-Rebuild, Job-Allowlist."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import recurring


SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS)
import wiki_hygiene  # noqa: E402


class WikiScanTests(unittest.TestCase):
    def _tree(self, tmp):
        os.makedirs(os.path.join(tmp, "concepts"))
        os.makedirs(os.path.join(tmp, "sources"))
        with open(os.path.join(tmp, "concepts", "Foo.md"), "w", encoding="utf-8") as f:
            f.write("Siehe [[Bar]] und [[MissingPage]] und [[used]].\n")
        with open(os.path.join(tmp, "concepts", "Bar.md"), "w", encoding="utf-8") as f:
            f.write("ok\n")
        with open(os.path.join(tmp, "sources", "used.md"), "w", encoding="utf-8") as f:
            f.write("source used\n")
        with open(os.path.join(tmp, "sources", "orphan.md"), "w", encoding="utf-8") as f:
            f.write("nobody links here\n")

    def test_dead_links_and_orphans(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._tree(tmp)
            res = wiki_hygiene.scan_wiki(tmp)
            targets = {d["target"] for d in res["dead_links"]}
            self.assertIn("MissingPage", targets)
            self.assertNotIn("Bar", targets)
            self.assertEqual(res["orphaned_sources_count"], 1)
            self.assertEqual(res["orphaned_sources"], ["sources/orphan.md"])
            self.assertEqual(res["secret_hits_count"], 0)

    def test_digest_adds_pages_and_keeps_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._tree(tmp)
            cache = os.path.join(tmp, ".openclaw-wiki", "cache")
            os.makedirs(cache)
            old = {
                "pageCounts": {"concept": 1},
                "claimCount": 4,
                "claimHealth": {"contested": 1},
                "contradictionClusters": ["x"],
                "pages": [
                    {
                        "id": "concept.concepts.Foo",
                        "title": "Foo",
                        "kind": "concept",
                        "path": "concepts/Foo.md",
                        "claimCount": 4,
                        "topClaims": [{"id": "c1"}],
                    },
                    {
                        "id": "gone",
                        "title": "Gone",
                        "kind": "concept",
                        "path": "concepts/Deleted.md",
                    },
                ],
            }
            path = os.path.join(cache, "agent-digest.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(old, f)
            notes, sources, stems, md_files = wiki_hygiene._walk_wiki(tmp)
            info = wiki_hygiene.rebuild_digest(tmp, md_files)
            self.assertTrue(info["ok"])
            with open(path, encoding="utf-8") as f:
                digest = json.load(f)
            paths = {p["path"] for p in digest["pages"]}
            self.assertIn("concepts/Foo.md", paths)
            self.assertIn("concepts/Bar.md", paths)
            self.assertNotIn("concepts/Deleted.md", paths)
            foo = next(p for p in digest["pages"] if p["path"] == "concepts/Foo.md")
            self.assertEqual(foo["claimCount"], 4)
            self.assertEqual(digest["claimCount"], 4)
            self.assertGreaterEqual(info["dropped_missing_file"], 1)


class WikiTrashTests(unittest.TestCase):
    def _tree(self, tmp):
        os.makedirs(os.path.join(tmp, "concepts"))
        os.makedirs(os.path.join(tmp, "syntheses"))
        os.makedirs(os.path.join(tmp, "sources", "grok-sessions"))
        os.makedirs(os.path.join(tmp, "summaries"))
        with open(os.path.join(tmp, "AGENTS.md"), "w", encoding="utf-8") as f:
            f.write("# contract\n")
        with open(os.path.join(tmp, "concepts", "Keep.md"), "w", encoding="utf-8") as f:
            f.write("Siehe [[used]] und [[bar]].\n")
        with open(os.path.join(tmp, "syntheses", "KeepSynth.md"), "w", encoding="utf-8") as f:
            f.write("ok\n")
        with open(os.path.join(tmp, "sources", "used.md"), "w", encoding="utf-8") as f:
            f.write("linked\n")
        with open(os.path.join(tmp, "sources", "orphan.md"), "w", encoding="utf-8") as f:
            f.write("nobody\n")
        with open(
            os.path.join(tmp, "sources", "unsafe-local-schulung-abc.md"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("unsafe\n")
        with open(os.path.join(tmp, "summaries", "crumb.md"), "w", encoding="utf-8") as f:
            f.write("session crumb\n")
        with open(
            os.path.join(tmp, "sources", "grok-sessions", "sess.md"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("raw chat\n")
        with open(os.path.join(tmp, "concepts", "Bar.md"), "w", encoding="utf-8") as f:
            f.write("live stem\n")

    def test_plan_trash_allow_and_deny(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._tree(tmp)
            scan = wiki_hygiene.scan_wiki(tmp)
            rels = set(wiki_hygiene.plan_trash(tmp, scan))
            self.assertIn("summaries/crumb.md", rels)
            self.assertIn("sources/grok-sessions/sess.md", rels)
            self.assertIn("sources/unsafe-local-schulung-abc.md", rels)
            self.assertIn("sources/orphan.md", rels)
            self.assertNotIn("sources/used.md", rels)
            self.assertNotIn("concepts/Keep.md", rels)
            self.assertNotIn("concepts/Bar.md", rels)
            self.assertNotIn("syntheses/KeepSynth.md", rels)
            self.assertNotIn("AGENTS.md", rels)

    def test_apply_moves_to_dated_trash_and_drops_empty_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._tree(tmp)
            scan = wiki_hygiene.scan_wiki(tmp)
            plan = wiki_hygiene.plan_trash(tmp, scan)
            moved = wiki_hygiene.apply_trash(tmp, plan, day="2026-08-28")
            self.assertGreaterEqual(moved, 4)
            self.assertFalse(os.path.isfile(os.path.join(tmp, "summaries", "crumb.md")))
            self.assertTrue(
                os.path.isfile(
                    os.path.join(
                        tmp, "_hygiene-trash", "2026-08-28", "summaries", "crumb.md"
                    )
                )
            )
            self.assertTrue(os.path.isfile(os.path.join(tmp, "concepts", "Keep.md")))
            self.assertTrue(os.path.isfile(os.path.join(tmp, "sources", "used.md")))
            self.assertFalse(os.path.isdir(os.path.join(tmp, "summaries")))
            self.assertFalse(os.path.isdir(os.path.join(tmp, "sources", "grok-sessions")))

    def test_purge_trash_older_than_30_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.path.join(tmp, "_hygiene-trash", "2026-07-01", "summaries")
            os.makedirs(old)
            with open(os.path.join(old, "x.md"), "w", encoding="utf-8") as f:
                f.write("x\n")
            keep = os.path.join(tmp, "_hygiene-trash", "2026-08-20", "summaries")
            os.makedirs(keep)
            with open(os.path.join(keep, "y.md"), "w", encoding="utf-8") as f:
                f.write("y\n")
            n = wiki_hygiene.purge_trash(
                tmp, today="2026-08-28", retention_days=30
            )
            self.assertGreaterEqual(n, 1)
            self.assertFalse(os.path.isdir(os.path.join(tmp, "_hygiene-trash", "2026-07-01")))
            self.assertTrue(
                os.path.isfile(
                    os.path.join(tmp, "_hygiene-trash", "2026-08-20", "summaries", "y.md")
                )
            )

    def test_unwrap_links_to_trashed_stems(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._tree(tmp)
            note = os.path.join(tmp, "concepts", "Keep.md")
            with open(note, "w", encoding="utf-8") as f:
                f.write("Siehe [[sess]] und [[crumb|Krümel]] und [[used]].\n")
            n = wiki_hygiene.unwrap_links_to_trashed(
                tmp,
                [
                    "sources/grok-sessions/sess.md",
                    "summaries/crumb.md",
                ],
            )
            self.assertGreaterEqual(n, 2)
            with open(note, encoding="utf-8") as f:
                body = f.read()
            self.assertNotIn("[[sess]]", body)
            self.assertNotIn("[[crumb|Krümel]]", body)
            self.assertIn("sess", body)
            self.assertIn("Krümel", body)
            self.assertIn("[[used]]", body)

    def test_fix_dead_link_when_stem_unique(self):

        with tempfile.TemporaryDirectory() as tmp:
            self._tree(tmp)
            n = wiki_hygiene.fix_unique_dead_links(tmp)
            with open(os.path.join(tmp, "concepts", "Keep.md"), encoding="utf-8") as f:
                body = f.read()
            self.assertIn("[[Bar]]", body)
            self.assertNotIn("[[bar]]", body)

    def test_collapse_pending_drops_hygiene_bullets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "pending-contract.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(
                    "# Offene Vertragsvorschläge\n\n"
                    "- 2026-08-20 · memory-wiki · Wiki-Hygiene: 66 tote Links, "
                    "1 verwaiste Sources, 0 Secrets · job td-wiki-hygiene\n"
                    "- 2026-08-21 · memory-wiki · Wiki-Hygiene: 66 tote Links, "
                    "1 verwaiste Sources, 0 Secrets · job td-wiki-hygiene\n"
                    "- 2026-08-21 · glyph-ui · etwas anderes · grok\n"
                )
            wiki_hygiene.collapse_pending(path)
            with open(path, encoding="utf-8") as f:
                body = f.read()
            self.assertNotIn("Wiki-Hygiene:", body)
            self.assertIn("etwas anderes", body)

    def test_apply_writes_report_not_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._tree(tmp)
            pending = os.path.join(tmp, "pending-contract.md")
            with open(pending, "w", encoding="utf-8") as f:
                f.write("# Offene\n")
            out = wiki_hygiene.run_hygiene(
                tmp,
                pending_path=pending,
                day="2026-08-28",
                apply=True,
            )
            self.assertTrue(out.get("applied"))
            report = os.path.join(tmp, "reports", "hygiene.md")
            self.assertTrue(os.path.isfile(report))
            with open(pending, encoding="utf-8") as f:
                self.assertNotIn("Wiki-Hygiene:", f.read())


class JobAllowTests(unittest.TestCase):

    def test_wiki_hygiene_on_allowlist_and_normalizes(self):
        path = recurring._resolve_job_script("wiki_hygiene.py")
        self.assertTrue(path and os.path.isfile(path))
        store = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "jobs",
            "recurring.json",
        )
        with open(store, encoding="utf-8") as f:
            data = json.load(f)
        raw = next(i for i in data["items"] if i.get("id") == "td-wiki-hygiene")
        norm = recurring._normalize_item(raw)
        self.assertIsNotNone(norm)
        self.assertEqual(norm["script"], "wiki_hygiene.py")
        self.assertEqual(norm["schedule"]["time"], "03:15")


if __name__ == "__main__":
    unittest.main()
