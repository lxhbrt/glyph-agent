# -*- coding: utf-8 -*-
"""Unit tests for CODE-Tools (Workspace + Shell-Whitelist + Grep/SearchReplace)."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config, code_tools, tool_registry


class CodeToolsTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = self._tmpdir.name
        self._old_roots = list(config.CODE_WORKSPACE_ROOTS)
        self._old_reg = getattr(config, "CODE_WORKSPACES_USE_REGISTRY", True)
        config.CODE_WORKSPACES_USE_REGISTRY = False
        config.CODE_WORKSPACE_ROOTS = [os.path.realpath(self.root)]
        self._old_backup = getattr(config, "CODE_BACKUP_DIR", None)
        config.CODE_BACKUP_DIR = os.path.join(self.root, ".backups")

    def tearDown(self):
        config.CODE_WORKSPACE_ROOTS = self._old_roots
        config.CODE_WORKSPACES_USE_REGISTRY = self._old_reg
        if self._old_backup is not None:
            config.CODE_BACKUP_DIR = self._old_backup
        self._tmpdir.cleanup()

    def test_write_read_list(self):
        r = code_tools.write_file("hello.txt", "hallo welt\n")
        self.assertTrue(r["applied"])
        self.assertTrue(r["created"])
        got = code_tools.read_file("hello.txt")
        self.assertEqual(got["content"], "hallo welt\n")
        listing = code_tools.list_dir(".")
        names = [e["name"] for e in listing["entries"]]
        self.assertIn("hello.txt", names)

    def test_write_backup_on_overwrite(self):
        code_tools.write_file("a.txt", "v1")
        r2 = code_tools.write_file("a.txt", "v2")
        self.assertTrue(r2["applied"])
        self.assertTrue(r2["backup"])
        self.assertEqual(code_tools.read_file("a.txt")["content"], "v2")

    def test_path_escape_blocked(self):
        with self.assertRaises(ValueError):
            code_tools.read_file("/etc/passwd")
        with self.assertRaises(ValueError):
            code_tools.read_file("../outside.txt")

    def test_shell_whitelist(self):
        ok, _ = code_tools.shell_allowed("ls -la")
        self.assertTrue(ok)
        ok, reason = code_tools.shell_allowed("rm -rf /")
        self.assertFalse(ok)
        self.assertTrue(reason)
        ok, _ = code_tools.shell_allowed("git status")
        self.assertTrue(ok)
        ok, _ = code_tools.shell_allowed("git add .")
        self.assertTrue(ok)
        ok, _ = code_tools.shell_allowed("git commit -m 'x'")
        self.assertTrue(ok)
        ok, _ = code_tools.shell_allowed("git stash")
        self.assertTrue(ok)
        # push: elevated — ohne Flag abgelehnt, mit Flag erlaubt
        ok, reason = code_tools.shell_allowed("git push origin main")
        self.assertFalse(ok)
        self.assertIn("Elevated", reason)
        ok, _ = code_tools.shell_allowed("git push origin main", allow_elevated=True)
        self.assertTrue(ok)
        ok, _ = code_tools.shell_allowed("mkdir foo")
        self.assertTrue(ok)
        ok, _ = code_tools.shell_allowed("touch bar.txt")
        self.assertTrue(ok)
        ok, _ = code_tools.shell_allowed("cp a b")
        self.assertTrue(ok)
        ok, _ = code_tools.shell_allowed("diff a b")
        self.assertTrue(ok)
        ok, _ = code_tools.shell_allowed("python3 script.py")
        self.assertTrue(ok)
        ok, _ = code_tools.shell_allowed("node app.js")
        self.assertTrue(ok)
        ok, _ = code_tools.shell_allowed("sudo ls")
        self.assertFalse(ok)
        ok, _ = code_tools.shell_allowed("echo $(whoami)")
        self.assertFalse(ok)
        # Compound: elevated
        ok, reason = code_tools.shell_allowed(
            "git status --short && echo done"
        )
        self.assertFalse(ok)
        self.assertIn("Elevated", reason)
        ok, _ = code_tools.shell_allowed(
            "git status --short && echo done", allow_elevated=True
        )
        self.assertTrue(ok)
        ok, reason = code_tools.shell_allowed("git status --short; git log -1")
        self.assertFalse(ok)
        ok, reason = code_tools.shell_allowed("ls | head")
        self.assertFalse(ok)
        # Einzelbefehl bleibt erlaubt
        ok, _ = code_tools.shell_allowed("git status --short")
        self.assertTrue(ok)

    def test_shell_classify_service_elevated(self):
        kind, risk = code_tools.shell_classify("npm run service:install")
        self.assertEqual(kind, "elevated")
        self.assertTrue(risk)

    def test_permission_write_free_under_rw(self):
        d = code_tools.permission_decision(
            "WriteFile", {"path": "x.txt", "content": "hi"}
        )
        self.assertEqual(d["action"], "allow")
        d2 = code_tools.permission_decision(
            "RunCommand", {"command": "git status"}
        )
        self.assertEqual(d2["action"], "allow")
        d3 = code_tools.permission_decision(
            "RunCommand", {"command": "git push"}
        )
        self.assertEqual(d3["action"], "confirm")
        self.assertTrue(d3["elevated"])
        d4 = code_tools.permission_decision(
            "RunCommand", {"command": "rm -rf /"}
        )
        self.assertEqual(d4["action"], "deny")

    def test_write_execute_without_popup_confirm(self):
        """r+w: WriteFile läuft mit auto-confirm (Policy allow)."""
        res = tool_registry.execute(
            "WriteFile",
            {"path": "free.txt", "content": "hello\n"},
            confirm=lambda *_: True,
            mode="code",
        )
        self.assertTrue(res["ok"])
        self.assertEqual(code_tools.read_file("free.txt")["content"], "hello\n")

    def test_elevated_compound_runs(self):
        res = code_tools.run_command(
            "echo a && echo b",
            allow_elevated=True,
        )
        self.assertEqual(res["exit_code"], 0)
        self.assertIn("a", res["stdout"])
        self.assertIn("b", res["stdout"])

    def test_run_command_echo(self):
        res = code_tools.run_command("echo hello-code")
        self.assertEqual(res["exit_code"], 0)
        self.assertIn("hello-code", res["stdout"])

    def test_read_file_offset_limit(self):
        code_tools.write_file("lines.txt", "L1\nL2\nL3\nL4\nL5\n")
        got = code_tools.read_file("lines.txt", offset=2, limit=2)
        self.assertEqual(got["content"], "L2\nL3\n")
        self.assertEqual(got["offset"], 2)
        self.assertEqual(got["limit"], 2)
        self.assertEqual(got["total_lines"], 5)
        self.assertTrue(got["truncated"])

    def test_list_dir_recursive(self):
        os.makedirs(os.path.join(self.root, "sub", "deep"), exist_ok=True)
        code_tools.write_file("sub/a.txt", "x")
        code_tools.write_file("sub/deep/b.txt", "y")
        listing = code_tools.list_dir(".", recursive=True, max_depth=2)
        names = [e["name"] for e in listing["entries"]]
        self.assertTrue(any("a.txt" in n for n in names))
        self.assertTrue(listing.get("recursive"))

    def test_grep_finds_match(self):
        code_tools.write_file("src.py", "def hello():\n    return 42\n")
        code_tools.write_file("other.txt", "nope\n")
        res = code_tools.grep("hello", path=".")
        self.assertGreaterEqual(res["count"], 1)
        self.assertTrue(any("hello" in h["text"] for h in res["hits"]))
        self.assertIn(res["engine"], ("rg", "python"))

    def test_grep_outside_blocked(self):
        with self.assertRaises(ValueError):
            code_tools.grep("root", path="/etc")

    def test_search_replace_one_hit(self):
        code_tools.write_file("edit.py", "alpha\nbeta\ngamma\n")
        r = code_tools.search_replace("edit.py", "beta", "BETA")
        self.assertTrue(r.get("applied") or r.get("replaced"))
        self.assertEqual(code_tools.read_file("edit.py")["content"], "alpha\nBETA\ngamma\n")

    def test_search_replace_zero_hits(self):
        code_tools.write_file("edit2.py", "only once\n")
        with self.assertRaises(ValueError):
            code_tools.search_replace("edit2.py", "missing", "x")

    def test_search_replace_multi_hits(self):
        code_tools.write_file("edit3.py", "xx\nxx\n")
        with self.assertRaises(ValueError) as cm:
            code_tools.search_replace("edit3.py", "xx", "yy")
        self.assertIn("2", str(cm.exception))

    def test_registry_code_tools(self):
        names = {t["name"] for t in tool_registry.CODE_TOOLS}
        for n in ("ListDir", "ReadFile", "Grep", "SearchReplace", "WriteFile", "RunCommand"):
            self.assertIn(n, names)
        # Grep is read-only; SearchReplace is write
        self.assertFalse(tool_registry.CODE_TOOL_MAP["Grep"]["write"])
        self.assertTrue(tool_registry.CODE_TOOL_MAP["SearchReplace"]["write"])
        # execute Grep
        code_tools.write_file("g.py", "findme\n")
        res = tool_registry.execute(
            "Grep", {"pattern": "findme", "path": "."}, mode="code"
        )
        self.assertTrue(res["ok"])
        self.assertGreaterEqual(res["result"]["count"], 1)

    def test_config_max_rounds_default(self):
        self.assertGreaterEqual(int(config.CODE_MAX_ROUNDS), 32)

    def test_workspace_roots_only_existing(self):
        roots = code_tools.workspace_roots()
        for r in roots:
            self.assertTrue(os.path.isdir(r), r)


class EmptyRegistryRootsTests(unittest.TestCase):
    """Store geladen + nichts accessible → workspace_roots() == [] (kein Default-rw)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.store = os.path.join(self.root, "workspaces.json")
        self.ws = os.path.realpath(os.path.join(self.root, "only"))
        os.makedirs(self.ws)

        import core.workspaces_registry as wr
        from core import bind_store

        self.wr = wr
        self.bind_store = bind_store
        self._orig_dir = wr.GLYPH_DIR
        self._orig_store = wr.USER_STORE
        self._old_reg = getattr(config, "CODE_WORKSPACES_USE_REGISTRY", True)
        self._old_roots = list(config.CODE_WORKSPACE_ROOTS)
        wr.GLYPH_DIR = self.root
        wr.USER_STORE = self.store
        bind_store._mtime_cache.clear()
        with open(self.store, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "workspaces": []}, f)
        config.CODE_WORKSPACES_USE_REGISTRY = True
        config.CODE_WORKSPACE_ROOTS = [os.path.realpath(self.root)]

    def tearDown(self):
        self.wr.GLYPH_DIR = self._orig_dir
        self.wr.USER_STORE = self._orig_store
        config.CODE_WORKSPACES_USE_REGISTRY = self._old_reg
        config.CODE_WORKSPACE_ROOTS = self._old_roots
        self.bind_store._mtime_cache.clear()
        self._tmp.cleanup()

    def test_disable_last_rw_roots_empty(self):
        item = self.wr.attach(self.ws, mode="rw")["workspace"]
        self.assertEqual(code_tools.workspace_roots(), [self.ws])
        self.wr.update_workspace(item["id"], {"enabled": False})
        self.assertEqual(code_tools.workspace_roots(), [])
        # Fallback-Roots dürfen nicht aufgehen
        self.assertNotIn(os.path.realpath(self.root), code_tools.workspace_roots())


class AgentToolsExtTests(unittest.TestCase):
    """Leichte Tests für Agent-Erweiterungen (ohne externe CLIs/Netz)."""

    def test_wiki_aliases_in_registry(self):
        names = {t["name"] for t in tool_registry.TOOLS}
        for n in (
            "WikiSearch", "WikiGet", "WikiApply", "WikiStatus",
            "BrowseUrl", "ReadPdf", "MailList", "MailRead", "MessageSend",
            "ListVaultDir",
        ):
            self.assertIn(n, names)
        self.assertTrue(tool_registry.TOOL_MAP["WikiApply"]["write"])
        self.assertTrue(tool_registry.TOOL_MAP["MessageSend"]["write"])
        self.assertFalse(tool_registry.TOOL_MAP["WikiStatus"]["write"])
        self.assertFalse(tool_registry.TOOL_MAP["BrowseUrl"]["write"])

    def test_wiki_status_runs(self):
        from core import vault_tools
        res = vault_tools.wiki_status()
        self.assertIn("ok", res)
        # Wenn Digest existiert: available True
        if res.get("available"):
            self.assertTrue(res["ok"])
            self.assertIn("pageCounts", res)

    def test_message_send_needs_confirm(self):
        res = tool_registry.execute(
            "MessageSend",
            {"target": "x", "message": "hi"},
            confirm=None,
            mode="agent",
        )
        self.assertFalse(res["ok"])
        self.assertIn("Bestätigung", res["error"] or "")

    def test_pdf_missing_graceful(self):
        from core import pdf_tools
        # Außerhalb Vault → ValueError
        with self.assertRaises(ValueError):
            pdf_tools.read_pdf("/etc/passwd.pdf")


if __name__ == "__main__":
    unittest.main()
