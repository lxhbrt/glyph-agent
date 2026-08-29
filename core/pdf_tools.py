# -*- coding: utf-8 -*-
"""
PDF-Lesen für den Agenten-Modus (MODE=agent).

Nur Vault-Pfade (wie vault_tools), via `pdftotext` CLI (poppler).
Graceful degrade wenn CLI fehlt. Kein Shell-Arbitrary, fester argv.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from . import config, log, vault_tools

_MAX_PDF_CHARS = 40_000
_DEFAULT_TIMEOUT = 30


def _pdftotext_bin():
    for cand in (
        os.environ.get("PDFTOTEXT_BIN"),
        "/opt/homebrew/bin/pdftotext",
        "/usr/local/bin/pdftotext",
        shutil.which("pdftotext"),
    ):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def _resolve_pdf_path(path):
    """Vault-Pfad zu PDF auflösen; BLOCKED_DIRS greifen."""
    if not path or not str(path).strip():
        raise ValueError("ReadPdf: path fehlt")
    raw = str(path).strip()
    resolved = vault_tools._resolve_vault_path(raw)
    if not resolved:
        raise ValueError(vault_tools._outside_vault_error(raw))

    rel = vault_tools._rel_to_root(resolved)
    if vault_tools._is_blocked(rel):
        raise PermissionError(f"Geschützter Ordner — PDF-Zugriff verweigert: {rel}")
    if not resolved.lower().endswith(".pdf"):
        raise ValueError(f"Kein PDF-Pfad: {path}")
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"PDF nicht gefunden: {path}")
    return resolved, rel


def read_pdf(path, max_chars=None):
    """
    Extrahiert Text aus Vault-PDF via pdftotext.
    Liefert {path, content, chars, truncated, engine} oder graceful error-dict.
    """
    resolved, rel = _resolve_pdf_path(path)
    cap = int(max_chars or _MAX_PDF_CHARS)
    cap = max(500, min(cap, 200_000))

    bin_path = _pdftotext_bin()
    if not bin_path:
        log.log("read_pdf_skipped", path=rel, reason="pdftotext_missing")
        return {
            "ok": False,
            "path": rel,
            "content": "",
            "chars": 0,
            "truncated": False,
            "engine": None,
            "error": "PDF-Text nicht lesbar (Extraktion nicht verfügbar).",
        }

    try:
        proc = subprocess.run(
            [bin_path, "-layout", "-enc", "UTF-8", resolved, "-"],
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        log.log("read_pdf_timeout", path=rel)
        return {
            "ok": False,
            "path": rel,
            "content": "",
            "chars": 0,
            "truncated": False,
            "engine": "pdftotext",
            "error": f"pdftotext Timeout nach {_DEFAULT_TIMEOUT}s",
        }
    except OSError as e:
        return {
            "ok": False,
            "path": rel,
            "content": "",
            "chars": 0,
            "truncated": False,
            "engine": "pdftotext",
            "error": str(e),
        }

    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or f"exit {proc.returncode}"
        log.log("read_pdf_error", path=rel, error=err[:200])
        return {
            "ok": False,
            "path": rel,
            "content": "",
            "chars": 0,
            "truncated": False,
            "engine": "pdftotext",
            "error": err[:500],
        }

    text = proc.stdout or ""
    truncated = len(text) > cap
    text = text[:cap]
    log.log("read_pdf", path=rel, chars=len(text), truncated=truncated)
    return {
        "ok": True,
        "path": rel,
        "content": text,
        "chars": len(text),
        "truncated": truncated,
        "engine": "pdftotext",
        "error": None,
    }
