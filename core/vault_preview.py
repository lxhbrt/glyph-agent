# -*- coding: utf-8 -*-
"""Manuelle Ordner-Suche: Trefferliste für den °_Agent-Toggle (kein LLM)."""
import time

from . import retrieval, vault_tools
from .vault_web_fallback import run_deadline

_MAX_HITS = 12
_EXCERPT = 240
# Stay under glyph-ui.com Cloudflare HTTP timeout (100s) and UI proxy (90s).
PREVIEW_BUDGET_S = 70


def preview_vault_hits(query, top_k=8, budget_s=None, now=None):
    """Namens-Treffer auf Disk + VaultFind-Eltern (+ ListVaultDir bei Inventar).

    Liefert {ok, query, status, hits:[{id, kind, path, title, excerpt, score}]}.
    Pfade kanonisch `/VaultName/rel`. Ordner mit passendem Namen stehen vorn —
    auch wenn der Embedding-Index die Datei noch nicht kennt.
    Disk-Namen laufen vor VaultFind, damit ein hängendes Ollama nicht 502 erzeugt.
    """
    q = (query or "").strip()
    if not q:
        return {"ok": True, "query": "", "status": "empty", "hits": []}

    budget = PREVIEW_BUDGET_S if budget_s is None else float(budget_s)
    start = now if now is not None else time.monotonic()
    deadline = start + max(0.0, budget)

    files = []
    folders = {}
    seen_files = set()

    def _put_folder(path, score):
        canon = vault_tools.canon_vault_path(path)
        if not canon or canon in (".", "/"):
            return
        prev = folders.get(canon)
        if prev is None or _score_val(score) > _score_val(prev.get("score")):
            folders[canon] = _folder_hit(canon, score)

    def _put_file(hit):
        if not hit:
            return
        canon = vault_tools.canon_vault_path(hit["path"])
        if not canon:
            return
        hit = dict(hit)
        hit["path"] = canon
        hit["id"] = f"file:{canon}"
        if canon in seen_files:
            return
        seen_files.add(canon)
        files.append(hit)
        parent = _parent_folder(canon)
        if parent:
            _put_folder(parent, hit.get("score"))

    # 1) Dateiname/Ordnername auf Disk — bevor Index-Hits den Slot füllen
    try:
        named = vault_tools.match_vault_entries(q)
    except Exception:
        named = []
    named_folders = []
    for row in named:
        if not isinstance(row, dict):
            continue
        path = row.get("path") or ""
        if row.get("kind") == "folder":
            _put_folder(path, row.get("score"))
            named_folders.append(path)
        else:
            _put_file(_named_file_hit(row))

    def _vault_find():
        try:
            return retrieval.vault_find(q, top_k=top_k)
        except Exception:
            return {"status": "empty", "results": []}

    found = run_deadline(_vault_find, deadline, {"status": "empty", "results": []})
    if not isinstance(found, dict):
        found = {"status": "empty", "results": []}

    # 2) VaultFind (Index/Hybrid)
    for row in found.get("results") or []:
        if not isinstance(row, dict):
            continue
        _put_file(_file_hit(row))

    from . import tool_loop

    # 3) Inventar: nur den genannten Ordner listen, nicht alle Vault-Roots
    if tool_loop._is_vault_list_question(q):
        paths = []
        infer = getattr(tool_loop, "_infer_vault_list_paths", None)
        if callable(infer):
            paths = list(infer(q) or [])
        else:
            one = tool_loop._infer_vault_list_path(q)
            if one:
                paths = [one]
        if not paths and named_folders:
            paths = named_folders[:3]
        generic = not any(len(t) >= 6 for t in vault_tools._tokenize_query(q))
        if not paths and generic:
            paths = ["."]
        for lpath in paths[:3]:
            listing = None
            try:
                listing = vault_tools.list_vault_dir(lpath)
            except Exception:
                listing = None
            for entry in (listing or {}).get("entries") or []:
                if not isinstance(entry, dict):
                    continue
                path = str(entry.get("path") or "").strip()
                if not path:
                    continue
                if entry.get("type") == "dir":
                    _put_folder(path, None)
                else:
                    _put_file(
                        {
                            "id": f"file:{path}",
                            "kind": "file",
                            "path": path,
                            "title": str(entry.get("name") or path.rsplit("/", 1)[-1]),
                            "excerpt": "",
                            "score": None,
                        }
                    )

    # Namens-Ordner (max 4) + Dateien, dann restliche Ordner — Dateien nicht
    # von Index-Elternordnern aus dem 12er-Limit drücken.
    named_first = sorted(
        [h for h in folders.values() if _score_val(h.get("score")) >= 70],
        key=lambda h: (-_score_val(h.get("score")), h.get("path") or ""),
    )
    named_ids = {h["path"] for h in named_first}
    other_folders = [h for p, h in folders.items() if p not in named_ids]
    top_folders = named_first[:4]
    named_files = sorted(
        [h for h in files if _score_val(h.get("score")) >= 70],
        key=lambda h: (-_score_val(h.get("score")), h.get("path") or ""),
    )
    named_file_ids = {h.get("id") for h in named_files}
    other_files = [h for h in files if h.get("id") not in named_file_ids]
    hits = top_folders + named_files + other_folders + named_first[4:] + other_files
    hits = hits[:_MAX_HITS]
    fallback = None
    tried = []
    if not hits:
        from . import vault_web_fallback

        fb = vault_web_fallback.fallback_web_hits(
            q, vault_hit_count=0, deadline=deadline
        )
        hits = list(fb.get("hits") or [])[:_MAX_HITS]
        fallback = fb.get("source")
        tried = list(fb.get("tried") or [])
    status = "success" if hits else (found.get("status") or "empty")
    return {
        "ok": True,
        "query": q,
        "status": status,
        "hits": hits,
        "selected": len(hits),
        "sources": [h["path"] for h in hits if h.get("kind") == "file"],
        "fallback": fallback,
        "tried": tried,
    }


def _score_val(score):
    try:
        return float(score) if score is not None else -1.0
    except (TypeError, ValueError):
        return -1.0


def _named_file_hit(row):
    path = str(row.get("path") or "").strip()
    if not path:
        return None
    title = str(row.get("title") or path.rsplit("/", 1)[-1] or path)
    return {
        "id": f"file:{path}",
        "kind": "file",
        "path": path,
        "title": title,
        "excerpt": str(row.get("excerpt") or ""),
        "score": row.get("score"),
    }


def _file_hit(row):
    path = str(row.get("path") or "").strip()
    if not path:
        return None
    title = str(row.get("title") or path.rsplit("/", 1)[-1] or path)
    excerpt = str(row.get("text") or row.get("section") or "").strip()
    if len(excerpt) > _EXCERPT:
        excerpt = excerpt[:_EXCERPT].rstrip() + "…"
    score = row.get("score")
    try:
        score = float(score) if score is not None else None
    except (TypeError, ValueError):
        score = None
    return {
        "id": f"file:{path}",
        "kind": "file",
        "path": path,
        "title": title,
        "excerpt": excerpt,
        "score": score,
    }


def _folder_hit(path, score):
    path = vault_tools.canon_vault_path(path)
    title = path.rstrip("/").rsplit("/", 1)[-1] or path
    return {
        "id": f"folder:{path}",
        "kind": "folder",
        "path": path,
        "title": title,
        "excerpt": "",
        "score": score,
    }


def _parent_folder(path):
    p = vault_tools.canon_vault_path(path)
    if p.count("/") < 2:
        return ""
    return p.rsplit("/", 1)[0]
