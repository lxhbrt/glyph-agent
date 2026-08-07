# -*- coding: utf-8 -*-
"""
Code-Tools für den ^_Code-Modus (C′).

Nur Workspace-Roots, Diff+Backup beim Schreiben, Shell nur per Whitelist.
Kein VaultFind, keine Obsidian-Pfade — getrennte Sicherheitsdomäne vom Vault-Agenten.
"""
from __future__ import annotations

import difflib
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

from . import config, log

# Absolute Maxima (Defense in Depth)
_MAX_READ_BYTES = 512 * 1024
_MAX_WRITE_BYTES = 1024 * 1024
_MAX_LIST_ENTRIES = 200
_MAX_CMD_OUTPUT = 80_000


def workspace_roots():
    """Kanonische erlaubte Roots (realpath)."""
    roots = []
    for r in getattr(config, "CODE_WORKSPACE_ROOTS", []) or []:
        r = (r or "").strip()
        if not r:
            continue
        try:
            roots.append(os.path.realpath(r))
        except OSError:
            continue
    return roots


def _resolve_path(path):
    """
    Löst path relativ zu einem Workspace-Root auf.
    Absoluter Pfad: muss unter einem Root liegen.
    Relativer Pfad: erster Root, der den Pfad enthält / join mit erstem Root.
    Liefert (abs_path, root) oder (None, None).
    """
    if path is None or str(path).strip() == "":
        return None, None
    raw = str(path).strip()
    roots = workspace_roots()
    if not roots:
        return None, None

    if os.path.isabs(raw):
        cand = os.path.realpath(raw)
        for root in roots:
            if cand == root or cand.startswith(root + os.sep):
                return cand, root
        return None, None

    # Relativ: unter dem ersten Root (oder dem, der als Prefix passt)
    for root in roots:
        cand = os.path.realpath(os.path.join(root, raw))
        if cand == root or cand.startswith(root + os.sep):
            return cand, root
    return None, None


def _rel_display(abs_path, root):
    try:
        return os.path.relpath(abs_path, root)
    except ValueError:
        return abs_path


def list_dir(path="."):
    """Listet Verzeichnis unter Workspace-Root (nicht rekursiv)."""
    abs_path, root = _resolve_path(path or ".")
    if not abs_path:
        raise ValueError(f"Pfad außerhalb der Workspace-Roots: {path}")
    if not os.path.isdir(abs_path):
        raise ValueError(f"Kein Verzeichnis: {path}")
    entries = []
    try:
        names = sorted(os.listdir(abs_path))
    except OSError as e:
        raise ValueError(str(e)) from e
    for name in names[:_MAX_LIST_ENTRIES]:
        full = os.path.join(abs_path, name)
        kind = "dir" if os.path.isdir(full) else "file"
        try:
            size = os.path.getsize(full) if kind == "file" else None
        except OSError:
            size = None
        entries.append({"name": name, "kind": kind, "size": size})
    log.log("code_list_dir", path=_rel_display(abs_path, root), n=len(entries))
    return {
        "path": _rel_display(abs_path, root),
        "root": root,
        "entries": entries,
        "truncated": len(names) > _MAX_LIST_ENTRIES,
    }


def read_file(path, max_bytes=None):
    """Liest Textdatei (UTF-8, replacement) innerhalb der Roots."""
    abs_path, root = _resolve_path(path)
    if not abs_path:
        raise ValueError(f"Pfad außerhalb der Workspace-Roots: {path}")
    if not os.path.isfile(abs_path):
        raise ValueError(f"Datei nicht gefunden: {path}")
    limit = int(max_bytes or _MAX_READ_BYTES)
    with open(abs_path, "rb") as f:
        data = f.read(limit + 1)
    truncated = len(data) > limit
    data = data[:limit]
    text = data.decode("utf-8", errors="replace")
    log.log("code_read_file", path=_rel_display(abs_path, root), chars=len(text))
    return {
        "path": _rel_display(abs_path, root),
        "content": text,
        "chars": len(text),
        "truncated": truncated,
    }


def propose_write(path, content):
    """Diff-Vorschau ohne Schreiben."""
    abs_path, root = _resolve_path(path)
    if not abs_path:
        raise ValueError(f"Pfad außerhalb der Workspace-Roots: {path}")
    content = content if content is not None else ""
    if len(content.encode("utf-8")) > _MAX_WRITE_BYTES:
        raise ValueError(f"Inhalt zu groß (>{_MAX_WRITE_BYTES} Bytes)")
    old = ""
    exists = os.path.isfile(abs_path)
    if exists:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            old = f.read()
    old_lines = old.splitlines(keepends=True)
    new_lines = str(content).splitlines(keepends=True)
    rel = _rel_display(abs_path, root)
    diff = "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
            lineterm="",
        )
    )
    return {
        "path": rel,
        "diff": diff,
        "changed": old != content,
        "exists": exists,
        "old_chars": len(old),
        "new_chars": len(content),
    }


def write_file(path, content):
    """
    Schreibt Datei mit Backup (wie Vault ApplyEdit, aber Workspace-Roots).
    Kein Löschen, kein Umbenennen.
    """
    abs_path, root = _resolve_path(path)
    if not abs_path:
        raise ValueError(f"Pfad außerhalb der Workspace-Roots: {path}")
    content = content if content is not None else ""
    raw = str(content).encode("utf-8")
    if len(raw) > _MAX_WRITE_BYTES:
        raise ValueError(f"Inhalt zu groß (>{_MAX_WRITE_BYTES} Bytes)")

    # Keine Directory-Traversal-Reste, Parent muss unter Root bleiben
    parent = os.path.dirname(abs_path)
    parent_real = os.path.realpath(parent) if os.path.isdir(parent) else os.path.realpath(
        os.path.join(root, os.path.relpath(parent, root) if parent.startswith(root) else parent)
    )
    # Parent anlegen nur wenn unter root
    if not (parent == root or parent.startswith(root + os.sep) or os.path.realpath(parent).startswith(root + os.sep) or os.path.realpath(parent) == root):
        # join-basiert: parent of new file under root
        if not abs_path.startswith(root + os.sep) and abs_path != root:
            raise ValueError(f"Unsicherer Parent-Pfad: {path}")

    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    old = ""
    if os.path.isfile(abs_path):
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            old = f.read()
    if old == content:
        return {
            "path": _rel_display(abs_path, root),
            "applied": False,
            "reason": "no_change",
        }

    backup_dir = getattr(config, "CODE_BACKUP_DIR", None) or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "vault", "code_backups"
    )
    os.makedirs(backup_dir, exist_ok=True)
    rel = _rel_display(abs_path, root)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe = rel.replace(os.sep, "__").replace("/", "__")
    backup_file = os.path.join(backup_dir, f"{safe}.{stamp}.bak")
    if old:
        with open(backup_file, "w", encoding="utf-8") as f:
            f.write(old)

    tmp = abs_path + ".tmp-glyph-code"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, abs_path)

    log.log(
        "code_write_file",
        path=rel,
        backup=os.path.basename(backup_file) if old else None,
        old_chars=len(old),
        new_chars=len(content),
    )
    return {
        "path": rel,
        "applied": True,
        "backup": os.path.basename(backup_file) if old else None,
        "created": not bool(old),
    }


# --- Shell ---

# Explizit verbotene Muster (auch wenn Whitelist greifen würde)
_DENY_PATTERNS = [
    r"\brm\b",
    r"\bmv\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bsudo\b",
    r"\bdoas\b",
    r"\bmkfs\b",
    r"\bdd\b",
    r">\s*/",
    r"\bcurl\b.*\|\s*(ba)?sh",
    r"\bwget\b.*\|\s*(ba)?sh",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bkill\b",
    r"\bkillall\b",
    r"\blaunchctl\b",
    r"\bdiskutil\b",
    r"\bsecurity\b",
    r"\bosascript\b",
    r"`",
    r"\$\(",
    r"&&\s*rm\b",
    r";\s*rm\b",
    r"\|\s*rm\b",
]


def _default_allow_patterns():
    return list(getattr(config, "CODE_SHELL_ALLOW", None) or [])


def shell_allowed(command):
    """True, wenn command die Whitelist passiert und kein Deny greift."""
    cmd = (command or "").strip()
    if not cmd:
        return False, "leerer Befehl"
    if len(cmd) > 2000:
        return False, "Befehl zu lang"
    if "\n" in cmd or "\r" in cmd:
        return False, "Mehrzeilige Befehle verboten"
    low = cmd.lower()
    for pat in _DENY_PATTERNS:
        if re.search(pat, cmd, re.IGNORECASE):
            return False, f"verbotenes Muster: {pat}"
    allows = _default_allow_patterns()
    if not allows:
        return False, "keine Shell-Whitelist konfiguriert"
    for pat in allows:
        try:
            if re.search(pat, cmd):
                return True, None
        except re.error:
            continue
    return False, "nicht in der Shell-Whitelist"


def run_command(command, cwd=None, timeout=None):
    """
    Führt einen Whitelist-Befehl unter einem Workspace-Root aus.
    shell=False mit shlex.split; kein bare shell=True.
    """
    ok, reason = shell_allowed(command)
    if not ok:
        raise ValueError(f"Shell abgelehnt: {reason}")

    roots = workspace_roots()
    if not roots:
        raise ValueError("Keine CODE_WORKSPACE_ROOTS konfiguriert")

    work = cwd or roots[0]
    abs_cwd, root = _resolve_path(work)
    if not abs_cwd or not os.path.isdir(abs_cwd):
        # fallback: first root
        abs_cwd, root = roots[0], roots[0]
        if cwd:
            raise ValueError(f"cwd außerhalb Workspace-Roots: {cwd}")

    timeout_s = int(timeout or getattr(config, "CODE_SHELL_TIMEOUT", 60) or 60)
    timeout_s = max(1, min(timeout_s, 120))

    try:
        argv = shlex.split(command)
    except ValueError as e:
        raise ValueError(f"Befehl nicht parsbar: {e}") from e
    if not argv:
        raise ValueError("leerer Befehl")

    # Nur erlaubte Binaries: erstes Token muss basename matchen (kein /usr/bin/rm-Escape
    # über absolute Pfade außerhalb) — absolute Pfade nur wenn Binary-Name whitelisted.
    bin_name = os.path.basename(argv[0])
    # Re-check allow on reconstructed simple form for basename
    ok2, reason2 = shell_allowed(command)
    if not ok2:
        raise ValueError(f"Shell abgelehnt: {reason2}")

    env = os.environ.copy()
    # Keine Secrets-Expansion erzwingen — PATH behalten, aber HOME ok
    env["LANG"] = env.get("LANG") or "en_US.UTF-8"

    log.log("code_run_command", cmd=command[:200], cwd=_rel_display(abs_cwd, root))
    try:
        proc = subprocess.run(
            argv,
            cwd=abs_cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        err = (e.stderr or "") if isinstance(e.stderr, str) else f"Timeout nach {timeout_s}s"
        return {
            "command": command,
            "cwd": _rel_display(abs_cwd, root),
            "exit_code": -1,
            "stdout": out[:_MAX_CMD_OUTPUT],
            "stderr": err[:_MAX_CMD_OUTPUT],
            "timeout": True,
        }
    except FileNotFoundError:
        raise ValueError(f"Befehl nicht gefunden: {bin_name}") from None

    stdout = (proc.stdout or "")[:_MAX_CMD_OUTPUT]
    stderr = (proc.stderr or "")[:_MAX_CMD_OUTPUT]
    return {
        "command": command,
        "cwd": _rel_display(abs_cwd, root),
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "timeout": False,
        "truncated": len(proc.stdout or "") > _MAX_CMD_OUTPUT
        or len(proc.stderr or "") > _MAX_CMD_OUTPUT,
    }


def preview_for_confirm(tool_name, args):
    """Kurzer Preview-Text für Glyph-Genehmigungsdialog."""
    args = args or {}
    if tool_name == "WriteFile":
        try:
            prop = propose_write(args.get("path"), args.get("content", ""))
            diff = (prop.get("diff") or "")[:2500]
            return f"WriteFile → {prop.get('path')}\n{diff or '(neue Datei / kein Diff)'}"
        except Exception as e:
            return f"WriteFile → {args.get('path')}: {e}"
    if tool_name == "RunCommand":
        return f"RunCommand → {args.get('command')}\ncwd={args.get('cwd') or '.'}"
    return f"{tool_name}: {args}"
