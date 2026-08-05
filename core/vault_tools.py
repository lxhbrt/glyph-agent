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
    Löst einen Pfad relativ zu einem der konfigurierten Vaults auf und stellt sicher,
    dass er innerhalb EINES davon bleibt (Block gegen ../-Pfadmanipulation).
    Liefert absoluten, kanonischen Pfad oder None (unsicher).
    """
    vault_roots = [os.path.realpath(v) for v in getattr(config, "VAULT_PATHS", [config.VAULT_PATH])]
    if os.path.isabs(relative_or_abs):
        cand = os.path.realpath(relative_or_abs)
        for v in vault_roots:
            if cand == v or cand.startswith(v + os.sep):
                return cand
        return None
    # Relative Pfade werden auf jeden Vault-Root bezogen; der erste Treffer gewinnt.
    for v in vault_roots:
        cand = os.path.realpath(os.path.join(v, relative_or_abs))
        if cand == v or cand.startswith(v + os.sep):
            return cand
    return None


def _root_for_path(abs_path):
    """Liefert den Vault-Root, zu dem ein absoluter Pfad gehört, oder None."""
    abs_path = os.path.realpath(abs_path)
    for v in getattr(config, "VAULT_PATHS", [config.VAULT_PATH]):
        vr = os.path.realpath(v)
        if abs_path == vr or abs_path.startswith(vr + os.sep):
            return vr
    return None


def _rel_to_root(resolved):
    """Relativer Pfad eines absoluten Vault-Pfads zu seinem Vault-Root (mit Vault-Präfix)."""
    root = _root_for_path(resolved)
    if root:
        rel = os.path.relpath(resolved, root)
        return os.path.join(os.path.basename(root), rel)
    return resolved


def _safe_md_name(path):
    """Erzwingt .md-Endung und erlaubt nur erlaubte Zeichen im Pfad."""
    if not path.endswith(".md"):
        path += ".md"
    # Erlaubt: Buchstaben/Ziffern, Leerzeichen, Bindestrich, Unterstrich, Schrägstrich, Punkt
    if re.search(r"[^A-Za-z0-9_\-./äöüÄÖÜß ]", os.path.basename(path)):
        return None
    return path


def _is_blocked(relpath):
    """True, wenn der Pfad in einen geschützten Ordner zeigt (case-insensitiv).
    Matching ist tolerant: Blocklist-Stichwort wird als Teilstring gegen den
    Ordnernamen geprüft (z. B. 'privat' trifft 'Privat', 'private', 'Privates')."""
    parts = relpath.replace(os.sep, "/").lower().split("/")
    blocked = [b.lower().strip() for b in (getattr(config, "BLOCKED_DIRS", []) or []) if b.strip()]
    for p in parts:
        for b in blocked:
            if b and (b in p or p in b):
                return True
    return False


# --- Lesen / Suchen ---

def search_vault(query, limit=20):
    """
    Durchsucht alle .md-Dateien im Vault nach einer Textzeichenkette (case-insensitive).
    Liefert Liste von {'path': relpath, 'hits': n}. Reine Leseoperation.
    """
    query_l = query.lower()
    results = []
    vault_roots = getattr(config, "VAULT_PATHS", [config.VAULT_PATH])
    for vroot in vault_roots:
        vroot_r = os.path.realpath(vroot)
        for root, _dirs, files in os.walk(vroot_r):
            # Obsidian-interne Ordner + Backups ausschließen
            relroot = os.path.relpath(root, vroot_r)
            if any(seg.startswith(".") for seg in relroot.split(os.sep)):
                continue
            if "backups" in relroot.split(os.sep):
                continue
            if _is_blocked(relroot):
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
                    rel = os.path.relpath(fpath, vroot_r)
                    results.append({"path": rel, "abs_path": fpath, "vault": os.path.basename(vroot_r), "hits": hits})
    results.sort(key=lambda r: r["hits"], reverse=True)
    log.log("search_vault", query=query, results=len(results))
    return results[:limit]


def read_note(path):
    """Liest eine Notiz (relativ zum Vault) und gibt {path, content, chars} zurück."""
    resolved = _resolve_vault_path(path)
    if not resolved or not resolved.endswith(".md"):
        raise ValueError(f"Ungültiger oder unsicherer Pfad: {path}")
    rel = _rel_to_root(resolved)
    if _is_blocked(rel):
        raise PermissionError(f"Geschützter Ordner — Zugriff verweigert: {rel}")
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"Notiz nicht gefunden: {path}")
    with open(resolved, encoding="utf-8", errors="replace") as f:
        content = f.read()
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
    rel = _rel_to_root(resolved)
    log.log("create_note", path=rel, chars=len(content))
    return {"path": rel, "created": True, "exists": False}


# --- Änderungen: Diff-Vorschau + gesichertes Anwenden ---

def _revision_path(resolved):
    """Ermittelt den nächsten Revisions-Pfad für eine Datei."""
    rel = _rel_to_root(resolved)
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
            backup=_rel_to_root(backup_file),
            old_chars=len(old_content), new_chars=len(new_content))
    return {"path": current["path"], "applied": True, "rev": rev,
            "backup": _rel_to_root(backup_file)}


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


# --- Optional: Obsidian CLI (kepano) unter Sicherheitsdach --------------------

def _obsidian_bin():
    """Pfad zur obsidian-CLI (Homebrew oder PATH), oder None."""
    import shutil
    for cand in (
        os.environ.get("OBSIDIAN_CLI"),
        "/opt/homebrew/bin/obsidian",
        "/usr/local/bin/obsidian",
        shutil.which("obsidian"),
    ):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def obsidian_open(path):
    """
    Öffnet eine Notiz in der Obsidian-App über die offizielle CLI (kepano).

    Sicherheit:
      - Pfad muss innerhalb eines erlaubten Vaults auflösbar sein (_resolve_vault_path)
      - BLOCKED_DIRS greifen wie bei read_note
      - Kein freier Shell-String aus dem Modell — nur fester CLI-Aufruf
      - Wenn CLI fehlt: klarer Fehler, kein Crash

    Liefert {ok, path, vault, opened, message}.
    """
    import subprocess
    if not path:
        raise ValueError("Pfad fehlt.")
    resolved = _resolve_vault_path(path)
    if not resolved or not resolved.endswith(".md"):
        raise ValueError(f"Ungültiger oder unsicherer Pfad: {path}")
    rel = _rel_to_root(resolved)
    if _is_blocked(rel):
        raise PermissionError(f"Geschützter Ordner — Obsidian-Open verweigert: {rel}")
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"Notiz nicht gefunden: {path}")

    root = _root_for_path(resolved)
    vault_name = os.path.basename(root) if root else ""
    # Relativ zum Vault-Root (Obsidian will vault-interne Pfade)
    note_in_vault = os.path.relpath(resolved, root) if root else path
    note_in_vault = note_in_vault.replace("\\", "/")

    bin_path = _obsidian_bin()
    if not bin_path:
        log.log("obsidian_open_skipped", path=rel, reason="cli_missing")
        return {
            "ok": False,
            "opened": False,
            "path": rel,
            "vault": vault_name,
            "message": "Obsidian-CLI nicht gefunden (obsidian binary). "
                       "In Obsidian: Settings → Advanced → Command line interface aktivieren.",
        }

    # CLI: obsidian open <file>  bzw. mit vault — Versionen variieren; try open path
    try:
        # Bevorzugt: URI-Schema open (funktioniert auch ohne CLI-Subcommands)
        # obsidian "obsidian://open?vault=...&file=..."
        from urllib.parse import quote
        uri = f"obsidian://open?vault={quote(vault_name)}&file={quote(note_in_vault)}"
        subprocess.run(
            ["open", uri],
            check=False,
            capture_output=True,
            timeout=10,
        )
        log.log("obsidian_open", path=rel, vault=vault_name, via="uri")
        return {
            "ok": True,
            "opened": True,
            "path": rel,
            "vault": vault_name,
            "message": f"Obsidian geöffnet: {vault_name} / {note_in_vault}",
        }
    except Exception as e:
        log.log("obsidian_open_error", path=rel, error=str(e))
        return {
            "ok": False,
            "opened": False,
            "path": rel,
            "vault": vault_name,
            "message": f"Obsidian-Open fehlgeschlagen: {e}",
        }
