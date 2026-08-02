# -*- coding: utf-8 -*-
"""
Vault-Werkzeuge — die kontrollierte Tool-Schicht für Obsidian-Zugriff.

Prinzip (Architektur-Regel): Eine Datei im Vault ist DATENQUELLE, nicht
vertrauenswürdige Anweisung. Diese Schicht erzwingt:
  - Zugriff NUR innerhalb des konfigurierten Vaults (kein ../-Escape)
  - Lesen und Schreiben getrennt
  - KEINE Löschung / KEINE Umbenennung
  - Vor jeder Änderung: Backup + Revisionsnummer
  - Schreiben nur über zentrale Funktion (apply_edit) mit Diff-Bestätigung

Werkzeuge als einfache Python-Funktionen (persönlicher Sandkasten, kein Framework).
"""
import difflib
import json
import os
import re
import time

from . import config, log


# --- Pfad-Sicherheit ---

def _resolve_vault_path(relative_or_abs):
    """
    Löst einen Pfad relativ zum Vault auf und stellt sicher, dass er
    innerhalb des Vaults bleibt (Block gegen ../-Pfadmanipulation).
    Liefert absoluten, kanonischen Pfad oder None (unsicher).
    """
    vault = os.path.realpath(config.VAULT_PATH)
    if os.path.isabs(relative_or_abs):
        cand = os.path.realpath(relative_or_abs)
    else:
        # Relative Pfade werden auf den Vault bezogen
        cand = os.path.realpath(os.path.join(vault, relative_or_abs))
    # Innerhalb des Vaults? (realpath verhindert Symlink-/..-Escape)
    if cand == vault or cand.startswith(vault + os.sep):
        return cand
    return None


def _safe_md_name(path):
    """Erzwingt .md-Endung und erlaubt nur erlaubte Zeichen im Pfad."""
    if not path.endswith(".md"):
        path += ".md"
    # Erlaubt: Buchstaben/Ziffern, Leerzeichen, Bindestrich, Unterstrich, Schrägstrich, Punkt
    if re.search(r"[^A-Za-z0-9_\-./äöüÄÖÜß ]", os.path.basename(path)):
        return None
    return path


# --- Lesen / Suchen ---

def search_vault(query, limit=20):
    """
    Durchsucht alle .md-Dateien im Vault nach einer Textzeichenkette (case-insensitive).
    Liefert Liste von {'path': relpath, 'hits': n}. Reine Leseoperation.
    """
    query_l = query.lower()
    results = []
    for root, _dirs, files in os.walk(config.VAULT_PATH):
        # Obsidian-interne Ordner + Backups ausschließen
        relroot = os.path.relpath(root, config.VAULT_PATH)
        if any(seg.startswith(".") for seg in relroot.split(os.sep)):
            continue
        if "backups" in relroot.split(os.sep):
            continue
        for fn in files:
            if not fn.endswith(".md"):
                continue
            fpath = os.path.join(root, fn)
            try:
                with open(fpath, encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                continue
            hits = content.lower().count(query_l)
            if hits:
                rel = os.path.relpath(fpath, config.VAULT_PATH)
                results.append({"path": rel, "hits": hits})
    results.sort(key=lambda r: r["hits"], reverse=True)
    log.log("search_vault", query=query, results=len(results))
    return results[:limit]


def read_note(path):
    """Liest eine Notiz (relativ zum Vault) und gibt {path, content, chars} zurück."""
    resolved = _resolve_vault_path(path)
    if not resolved or not resolved.endswith(".md"):
        raise ValueError(f"Ungültiger oder unsicherer Pfad: {path}")
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"Notiz nicht gefunden: {path}")
    with open(resolved, encoding="utf-8", errors="replace") as f:
        content = f.read()
    rel = os.path.relpath(resolved, config.VAULT_PATH)
    log.log("read_note", path=rel, chars=len(content))
    return {"path": rel, "content": content, "chars": len(content)}


# --- Erstellen ---

def create_note(path, content):
    """
    Legt eine neue Notiz an. Weigert sich, wenn die Datei bereits existiert
    (kein Überschreiben!). Liefert {path, created: True} oder {path, exists: True}.
    """
    name = _safe_md_name(path)
    if not name:
        raise ValueError(f"Ungültiger Notizname: {path}")
    resolved = _resolve_vault_path(name)
    if not resolved:
        raise ValueError(f"Pfad außerhalb des Vaults: {path}")
    if os.path.exists(resolved):
        log.log("create_note_skipped", path=path, reason="exists")
        return {"path": path, "created": False, "exists": True}
    os.makedirs(os.path.dirname(resolved), exist_ok=True)
    with open(resolved, "w", encoding="utf-8") as f:
        f.write(content)
    rel = os.path.relpath(resolved, config.VAULT_PATH)
    log.log("create_note", path=rel, chars=len(content))
    return {"path": rel, "created": True, "exists": False}


# --- Änderungen: Diff-Vorschau + gesichertes Anwenden ---

def _revision_path(resolved):
    """Ermittelt den nächsten Revisions-Pfad für eine Datei."""
    rel = os.path.relpath(resolved, config.VAULT_PATH)
    stem = rel.replace("/", "__").replace(".md", "")
    return os.path.join(config.BACKUP_DIR, f"{stem}.R{{n}}.md")


def propose_edit(path, new_content):
    """
    Erzeugt nur eine DIFF-VORSCHAU (ändert nichts!).
    Liefert {path, diff (Unified-Diff), changed: bool, old_len, new_len}.
    Der Nutzer entscheidet dann über apply_edit.
    """
    current = read_note(path)  # loggt lesen
    old = current["content"].splitlines(keepends=True)
    new = new_content.splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(
        old, new, fromfile=f"a/{path}", tofile=f"b/{path}", lineterm=""
    ))
    log.log("propose_edit", path=current["path"], changed=(old != new),
            diff_len=len(diff))
    return {
        "path": current["path"],
        "diff": diff,
        "changed": old != new,
        "old_chars": len(current["content"]),
        "new_chars": len(new_content),
    }


def apply_edit(path, new_content):
    """
    Wendet eine Änderung NUR nach Backup + Revisionsnummer an.
    1) liest den aktuellen Inhalt  2) legt Backup an (R<n>)
    3) schreibt atomar (Temp-Datei + rename)
    Weigert sich bei gleichem Inhalt. KEIN Löschen/Umbenennen.
    """
    current = read_note(path)
    resolved = _resolve_vault_path(path)
    if resolved is None:
        raise ValueError(f"Unsicherer Pfad: {path}")

    old_content = current["content"]
    if old_content == new_content:
        log.log("apply_edit_skipped", path=current["path"], reason="no_change")
        return {"path": current["path"], "applied": False, "reason": "no_change"}

    # Revisionsnummer bestimmen (Sidecar-Index nötig)
    rev = _next_revision(current["path"])
    backup_file = os.path.join(config.BACKUP_DIR, _backup_filename(current["path"], rev))
    with open(backup_file, "w", encoding="utf-8") as f:
        f.write(old_content)

    # Atomar schreiben: zuerst Temp, dann rename (kein halber Zustand)
    tmp = resolved + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new_content)
    os.replace(tmp, resolved)

    log.log("apply_edit", path=current["path"], rev=rev,
            backup=os.path.relpath(backup_file, config.VAULT_PATH),
            old_chars=len(old_content), new_chars=len(new_content))
    return {"path": current["path"], "applied": True, "rev": rev,
            "backup": os.path.relpath(backup_file, config.VAULT_PATH)}


def _next_revision(relpath):
    """Liest den Revisionsstand aus einem Sidecar-Index (SQLite-frei: JSON)."""
    idx_file = os.path.join(config.BACKUP_DIR, "revisions.json")
    data = {}
    if os.path.exists(idx_file):
        try:
            with open(idx_file, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}
    n = data.get(relpath, 0) + 1
    data[relpath] = n
    with open(idx_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return n


def _backup_filename(relpath, rev):
    stem = relpath.replace("/", "__").replace(".md", "")
    return f"{stem}.R{rev}.md"


def list_backups():
    """Listet gesicherte Revisionen auf (für Wiederherstellung/Transparenz)."""
    if not os.path.isdir(config.BACKUP_DIR):
        return []
    out = []
    for fn in sorted(os.listdir(config.BACKUP_DIR)):
        if fn.endswith(".md"):
            out.append(fn)
    return out
