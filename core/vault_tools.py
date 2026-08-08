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

# Stopwörter für Token-Suche (DE/EN-Rauschen). Datum/Zahlen werden nie gefiltert.
_SEARCH_STOP = frozenset({
    "die", "der", "das", "den", "dem", "des", "ein", "eine", "einer", "eines",
    "einen", "einem", "und", "oder", "im", "in", "am", "an", "auf", "bei",
    "mit", "von", "vom", "zu", "zum", "zur", "für", "fur", "ist", "sind",
    "war", "wie", "was", "welche", "welcher", "welches", "wo", "wer", "mir",
    "mein", "meine", "meinen", "meinem", "dir", "dein", "ich", "du", "wir",
    "uns", "auch", "noch", "nur", "nicht", "kein", "keine", "sich", "als",
    "aus", "nach", "über", "uber", "unter", "sollten", "sollte", "liegen",
    "liegt", "gibt", "habe", "hast", "hat", "haben", "sein", "seine", "ihrer",
    "ihren", "bitte", "mal", "etwa", "zb", "b", "z", "ob", "es", "dass",
    "daß", "hier", "dort", "diese", "dieser", "dieses", "doch", "schon",
    "ganz", "sehr", "mehr", "weniger", "alle", "alles", "jeder", "jede",
    "obsidian", "ordner", "sync", "dokkumente", "dokumente", "dateien",
    "datei", "notizen", "notiz", "rohnotizen", "weitere", "the", "a", "an",
    "of", "to", "for", "and", "or", "is", "are", "in", "on", "at", "by",
})


def _tokenize_query(query):
    """
    Zerlegt eine Nutzerfrage in Such-Tokens.
    Behält Daten/Zahlen (z. B. 2026-06-29); filtert Stopwörter und Minilänge.
    """
    raw = re.findall(r"[a-zA-Z0-9äöüÄÖÜß_\-./]+", (query or "").lower())
    tokens = []
    seen = set()
    for t in raw:
        t = t.strip("./-")
        if not t or t in seen:
            continue
        if any(c.isdigit() for c in t):
            tokens.append(t)
            seen.add(t)
            continue
        if len(t) < 3 or t in _SEARCH_STOP:
            continue
        tokens.append(t)
        seen.add(t)
    return tokens


def _is_archive_source_path(rel_path):
    """
    True bei OpenClaw-Wiki-Source-Kopien / Hash-Slug-Archiven — nicht die
    kanonischen Arbeitsdateien (z. B. HSEQ Sync Eingang/Fertig).
    """
    p = (rel_path or "").replace("\\", "/").lower().lstrip("/")
    if p.startswith("sources/") or "/sources/" in f"/{p}":
        return True
    if "unsafe-local" in p:
        return True
    # Hash-Slugs: …-70dc75d2-… oder …-d1978aae.md
    if re.search(r"-[0-9a-f]{8,}(?:-|\.md$)", p):
        return True
    return False


def _vault_priority_index(vault_name, vault_roots=None):
    """0 = primärer Vault (VAULT_PATHS[0]), höher = später / unbekannter."""
    roots = vault_roots or getattr(config, "VAULT_PATHS", [config.VAULT_PATH])
    name = (vault_name or "").strip()
    for i, v in enumerate(roots):
        if os.path.basename(os.path.realpath(v)) == name:
            return i
    return len(list(roots)) + 1


def path_source_rank(rel_path, vault_name=None, query=None):
    """
    Zusätzlicher Score für kanonische Arbeitsdateien vs. Archiv-Kopien.

    Ziel: Nutzer trifft gültige Live-Dateien (HSEQ Sync, Arbeitsfluss), nicht
    alte Wiki-Source-Nummern/Hash-Slugs aus OpenClaw memory-wiki/sources/.
    Positiv = bevorzugen, negativ = abwerten.
    """
    rel = (rel_path or "").replace("\\", "/").lstrip("/")
    rel_l = rel.lower()
    bonus = 0
    # Primär-Vault vor Neben-Vaults (Wiki, Archiv)
    pri = _vault_priority_index(vault_name)
    bonus += max(0, 24 - pri * 10)
    if _is_archive_source_path(rel):
        bonus -= 50
    # Arbeitsfluss-Roh-/Fertig-Notizen: kanonisch
    if "00 arbeitsfluss/eingang" in rel_l or "00 arbeitsfluss/fertig" in rel_l:
        bonus += 18
    q = (query or "").lower()
    if q:
        if "eingang" in q and "eingang" in rel_l:
            bonus += 12
        if "fertig" in q and "fertig" in rel_l:
            bonus += 12
    return bonus


def search_vault(query, limit=20):
    """
    Durchsucht alle .md-Dateien im Vault (case-insensitive).

    Scoring (Hybrid Keyword):
      - Token-Treffer im Dateinamen/Pfad (stark gewichtet, Body-Cap)
      - Token-Treffer im Inhalt (gecappt — lange Wiki-Kopien nicht überstimmen)
      - Vault-Priorität + Abwertung von sources/unsafe-local-Hash-Archiven
      - optional exakter Phrasen-Treffer im Inhalt (falls Query kurz)

    Liefert Liste von {'path', 'abs_path', 'vault', 'hits'}. Reine Leseoperation.
    """
    query = (query or "").strip()
    if not query:
        return []
    query_l = query.lower()
    tokens = _tokenize_query(query)
    results = []
    vault_roots = getattr(config, "VAULT_PATHS", [config.VAULT_PATH])
    for vault_i, vroot in enumerate(vault_roots):
        vroot_r = os.path.realpath(vroot)
        vault_name = os.path.basename(vroot_r)
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
                content_l = content.lower()
                fn_l = fn.lower()
                rel = os.path.relpath(fpath, vroot_r)
                rel_l = rel.lower().replace("\\", "/")
                score = 0
                # Exakte Phrase (nur sinnvoll bei kurzen Queries, z. B. Fachbegriff)
                if len(query_l) <= 64 and " " not in query_l.strip():
                    # Body-Cap: lange Archiv-Kopien sollen reine Datums-Queries nicht dominieren
                    score += min(content_l.count(query_l), 4) * 3
                    if query_l in fn_l or query_l in rel_l:
                        score += 12
                if tokens:
                    for tok in tokens:
                        name_hit = tok in fn_l or tok in rel_l
                        c = content_l.count(tok)
                        if name_hit:
                            # Dateiname/Pfad: stark; Body nur leicht (Cap)
                            score += 12 + min(c, 3)
                        elif c:
                            score += min(c, 6)
                else:
                    # Keine Tokens (nur Stopwörter): alter Phrasen-Modus
                    score += min(content_l.count(query_l), 8)
                if not score:
                    continue
                score += path_source_rank(rel, vault_name=vault_name, query=query)
                # feiner Tie-Breaker: früherer Vault bei Gleichstand
                score += max(0, 3 - vault_i) * 0.01
                if score > 0:
                    results.append({
                        "path": rel,
                        "abs_path": fpath,
                        "vault": vault_name,
                        "hits": score,
                    })
    results.sort(key=lambda r: r["hits"], reverse=True)
    log.log("search_vault", query=query, results=len(results), tokens=tokens[:12])
    return results[:limit]


def list_vault_dir(path="", limit=200, extensions=None):
    """
    Listet Dateien und Unterordner unter einem Vault-Pfad (nur Lesen).

    path: relativ zu einem Vault-Root, optional mit Vault-Präfix
          (z. B. "HSEQ Sync/00 Arbeitsfluss/Eingang" oder "00 Arbeitsfluss/Eingang").
          Leer / "." = Top-Level aller konfigurierten Vaults.
    extensions: optional Iterable wie [".md", ".pdf"]; None = alle Dateien
                (außer versteckten/.obsidian/backups).
    limit: max. Einträge (Default 200).

    Liefert {
      status, path, vault, entries: [{name, path, type, size?, mtime?}],
      count, truncated, error?
    }.
    """
    limit = max(1, min(int(limit or 200), 1000))
    ext_set = None
    if extensions:
        ext_set = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions}

    raw = (path or "").strip()
    if raw in ("", ".", "/"):
        # Top-Level: je Vault-Root die direkten Kinder
        entries = []
        for vroot in getattr(config, "VAULT_PATHS", [config.VAULT_PATH]):
            vroot_r = os.path.realpath(vroot)
            if not os.path.isdir(vroot_r):
                continue
            vname = os.path.basename(vroot_r)
            try:
                names = sorted(os.listdir(vroot_r), key=lambda s: s.lower())
            except OSError:
                continue
            for name in names:
                if name.startswith("."):
                    continue
                if name.lower() == "backups":
                    continue
                full = os.path.join(vroot_r, name)
                rel_prefixed = f"{vname}/{name}"
                if _is_blocked(rel_prefixed):
                    continue
                is_dir = os.path.isdir(full)
                if not is_dir and ext_set is not None:
                    _, e = os.path.splitext(name)
                    if e.lower() not in ext_set:
                        continue
                entry = {
                    "name": name,
                    "path": rel_prefixed,
                    "type": "dir" if is_dir else "file",
                    "vault": vname,
                }
                if not is_dir:
                    try:
                        st = os.stat(full)
                        entry["size"] = st.st_size
                        entry["mtime"] = int(st.st_mtime)
                    except OSError:
                        pass
                entries.append(entry)
                if len(entries) >= limit:
                    break
            if len(entries) >= limit:
                break
        log.log("list_vault_dir", path=".", count=len(entries))
        return {
            "status": "success",
            "path": ".",
            "vault": None,
            "entries": entries[:limit],
            "count": min(len(entries), limit),
            "truncated": len(entries) > limit,
            "error": None,
        }

    resolved = _resolve_vault_path(raw)
    if not resolved:
        log.log("list_vault_dir_denied", path=raw, reason="outside_or_invalid")
        return {
            "status": "error",
            "path": raw,
            "vault": None,
            "entries": [],
            "count": 0,
            "truncated": False,
            "error": f"Pfad außerhalb der Vaults oder ungültig: {raw}",
        }
    rel = _rel_to_root(resolved)
    if _is_blocked(rel):
        return {
            "status": "error",
            "path": rel,
            "vault": None,
            "entries": [],
            "count": 0,
            "truncated": False,
            "error": f"Geschützter Ordner — Zugriff verweigert: {rel}",
        }
    if not os.path.isdir(resolved):
        return {
            "status": "error",
            "path": rel,
            "vault": os.path.basename(_root_for_path(resolved) or ""),
            "entries": [],
            "count": 0,
            "truncated": False,
            "error": f"Kein Verzeichnis: {rel}",
        }

    vroot = _root_for_path(resolved)
    vname = os.path.basename(vroot) if vroot else ""
    entries = []
    try:
        names = sorted(os.listdir(resolved), key=lambda s: s.lower())
    except OSError as e:
        return {
            "status": "error",
            "path": rel,
            "vault": vname,
            "entries": [],
            "count": 0,
            "truncated": False,
            "error": str(e),
        }

    for name in names:
        if name.startswith("."):
            continue
        if name.lower() == "backups":
            continue
        full = os.path.join(resolved, name)
        child_rel = os.path.join(rel, name).replace("\\", "/")
        # blocked check auf Kind relativ zum Vault-Präfix
        if _is_blocked(child_rel):
            continue
        is_dir = os.path.isdir(full)
        if not is_dir and ext_set is not None:
            _, e = os.path.splitext(name)
            if e.lower() not in ext_set:
                continue
        entry = {
            "name": name,
            "path": child_rel,
            "type": "dir" if is_dir else "file",
            "vault": vname,
        }
        if not is_dir:
            try:
                st = os.stat(full)
                entry["size"] = st.st_size
                entry["mtime"] = int(st.st_mtime)
            except OSError:
                pass
        entries.append(entry)
        if len(entries) >= limit:
            break

    truncated = len(entries) >= limit and len(names) > limit
    log.log("list_vault_dir", path=rel, count=len(entries), truncated=truncated)
    return {
        "status": "success",
        "path": rel,
        "vault": vname,
        "entries": entries,
        "count": len(entries),
        "truncated": truncated,
        "error": None,
    }


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


# --- OpenClaw Wiki-Status (agent-digest, read-only) ---------------------------

def _wiki_digest_path():
    """Pfad zu agent-digest.json unter OpenClaw memory-wiki, oder None."""
    vault_roots = getattr(config, "VAULT_PATHS", [config.VAULT_PATH])
    for v in vault_roots:
        # Konvention: OpenClaw memory-wiki/.openclaw-wiki/cache/agent-digest.json
        cand = os.path.join(
            v, ".openclaw-wiki", "cache", "agent-digest.json"
        )
        if os.path.isfile(cand):
            return cand
        # Basename-Match falls Vault-Root anders heißt
        if "memory-wiki" in os.path.basename(os.path.realpath(v)).lower() or \
           "openclaw" in os.path.basename(os.path.realpath(v)).lower():
            cand2 = os.path.join(
                os.path.realpath(v), ".openclaw-wiki", "cache", "agent-digest.json"
            )
            if os.path.isfile(cand2):
                return cand2
    # Fallback: bekannter Default-Pfad
    home = os.path.expanduser("~")
    fallback = os.path.join(
        home, "ObsidianVaults", "OpenClaw memory-wiki",
        ".openclaw-wiki", "cache", "agent-digest.json",
    )
    if os.path.isfile(fallback):
        return fallback
    return None


def wiki_status():
    """
    Read-only Stats aus OpenClaw agent-digest.json.
    Liefert pageCounts, claimCount, claimHealth (gekürzt), page_sample_n.
    """
    path = _wiki_digest_path()
    if not path:
        log.log("wiki_status_missing")
        return {
            "ok": False,
            "available": False,
            "error": (
                "agent-digest.json nicht gefunden "
                "(erwartet unter OpenClaw memory-wiki/.openclaw-wiki/cache/)."
            ),
        }
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return {"ok": False, "available": False, "error": f"digest unlesbar: {e}"}

    pages = data.get("pages") or []
    # Keine vollen pages — nur Stats + kurze Stichprobe
    sample = []
    for p in pages[:8]:
        if not isinstance(p, dict):
            continue
        sample.append({
            "id": p.get("id"),
            "title": p.get("title"),
            "kind": p.get("kind") or p.get("pageType"),
            "path": p.get("path"),
        })
    claim_health = data.get("claimHealth") or {}
    # claimHealth kann verschachtelt sein — flach halten
    health_summary = {}
    if isinstance(claim_health, dict):
        for k, v in list(claim_health.items())[:12]:
            if isinstance(v, (int, float, str, bool)) or v is None:
                health_summary[k] = v
            elif isinstance(v, list):
                health_summary[k] = f"{len(v)} Einträge"
            elif isinstance(v, dict):
                health_summary[k] = {sk: sv for sk, sv in list(v.items())[:8]
                                     if isinstance(sv, (int, float, str, bool, type(None)))}
            else:
                health_summary[k] = str(type(v).__name__)

    log.log("wiki_status", path=path, pages=len(pages))
    return {
        "ok": True,
        "available": True,
        "digest_path": path,
        "pageCounts": data.get("pageCounts") or {},
        "claimCount": data.get("claimCount"),
        "claimHealth": health_summary,
        "contradictionClusters": len(data.get("contradictionClusters") or []),
        "pages_total": len(pages),
        "page_sample": sample,
        "error": None,
    }


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
