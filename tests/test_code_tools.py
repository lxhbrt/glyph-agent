# -*- coding: utf-8 -*-
"""Unit tests for CODE-Tools (Workspace + Shell-Whitelist)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config, code_tools


class CodeToolsTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = self._tmpdir.name
        self._old_roots = list(config.CODE_WORKSPACE_ROOTS)
        config.CODE_WORKSPACE_ROOTS = [os.path.realpath(self.root)]
        self._old_backup = getattr(config, "CODE_BACKUP_DIR", None)
        config.CODE_BACKUP_DIR = os.path.join(self.root, ".backups")

    def tearDown(self):
        config.CODE_WORKSPACE_ROOTS = self._old_roots
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
        ok, _ = code_tools.shell_allowed("sudo ls")
        self.assertFalse(ok)

    def test_run_command_echo(self):
        res = code_tools.run_command("echo hello-code")
        self.assertEqual(res["exit_code"], 0)
        self.assertIn("hello-code", res["stdout"])


if __name__ == "__main__":
    unittest.main()
