# -*- coding: utf-8 -*-
"""
Code-Workspace-Registry (SoT für ^_Code).

Nutzer:   ~/.glyph/workspaces.json
Modes:    r | rw | private  (Vault-Analog)

Hot-Reload: load() liest bei mtime-Änderung neu.
Kabelsalat-UI (Phase 2): attach / detach / update / public_snapshot.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from . import log

GLYPH_DIR = os.path.expanduser("~/.glyph")
USER_STORE = os.path.join(GLYPH_DIR, "workspaces.json")

_MODES = frozenset({"r", "rw", "private"})

_HOME = os.path.expanduser("~")
_SEED = [
    {
        "id": "glyph-ui",
        "name": "glyph-ui",
        "path": os.path.join(_HOME, "glyph-ui"),
        "mode": "rw",
        "primary": True,
    },
    {
        "id": "glyph-agent",
        "name": "glyph-agent",
        "path": os.path.join(_HOME, "glyph-agent"),
        "mode": "rw",
        "primary": False,
    },
    {
        "id": "openclaw-workspace",
        "name": "openclaw-workspace",
        "path": os.path.join(_HOME, ".openclaw", "workspace"),
        "mode": "r",
        "primary": False,
    },
]

_mtime_cache: Tuple[float, Optional[dict]] = (0.0, None)


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (name or "ws").strip().lower()).strip("-")
    return (s or "ws")[:48]


def _empty_store() -> dict:
    return {"version": 1, "workspaces": []}


def _normalize(raw: dict, order: int) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    path = str(raw.get("path") or "").strip()
    if not path:
        return None
    path = os.path.expanduser(path)
    try:
        path = os.path.realpath(path)
    except OSError:
        pass
    name = str(raw.get("name") or os.path.basename(path) or "Workspace").strip()
    mode = str(raw.get("mode") or "r").strip().lower()
    if mode == "r+w":
        mode = "rw"
    if mode not in _MODES:
        mode = "r"
    wid = str(raw.get("id") or "").strip() or _slug(name)
    return {
        "id": wid,
        "name": name[:120],
        "path": path,
        "mode": mode,
        "primary": bool(raw.get("primary")),
        "enabled": raw.get("enabled", True) is not False,
        "order": int(raw.get("order", order)),
        "exists": os.path.isdir(path),
    }


def _fix_primary(items: List[dict]) -> List[dict]:
    enabled = [w for w in items if w.get("enabled") and w.get("exists")]
    if not enabled:
        return items
    primaries = [w for w in enabled if w.get("primary")]
    if len(primaries) == 1:
        return items
    # keep first enabled as primary
    first_id = enabled[0]["id"]
    for w in items:
        w["primary"] = w["id"] == first_id and w.get("enabled") and w.get("exists")
    return items


def _seed_store() -> dict:
    workspaces = []
    for i, raw in enumerate(_SEED):
        w = _normalize({**raw}, i)
        if w and w["exists"]:
            workspaces.append(w)
    # Fallback: CODE_WORKSPACE_ROOTS / defaults from config if seed empty
    if not workspaces:
        try:
            from . import config
            for i, p in enumerate(getattr(config, "CODE_WORKSPACE_ROOTS", []) or []):
                w = _normalize(
                    {
                        "path": p,
                        "name": os.path.basename(p) or p,
                        "mode": "rw",
                        "primary": i == 0,
                    },
                    i,
                )
                if w and w["exists"]:
                    workspaces.append(w)
        except Exception:
            pass
    workspaces = _fix_primary(workspaces)
    log.log("workspaces_seeded", count=len(workspaces))
    return {"version": 1, "workspaces": workspaces, "seeded": True}


def load_store(*, force: bool = False) -> dict:
    """Lädt Nutzer-SoT; seedet einmalig wenn Datei fehlt."""
    global _mtime_cache
    os.makedirs(GLYPH_DIR, exist_ok=True)

    if not os.path.isfile(USER_STORE):
        store = _seed_store()
        save_store(store)
        try:
            mtime = os.path.getmtime(USER_STORE)
        except OSError:
            mtime = 0.0
        _mtime_cache = (mtime, store)
        return store

    try:
        mtime = os.path.getmtime(USER_STORE)
    except OSError:
        mtime = 0.0
    if not force and _mtime_cache[1] is not None and _mtime_cache[0] == mtime:
        return _mtime_cache[1]

    try:
        with open(USER_STORE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = _empty_store()
    if not isinstance(data, dict):
        data = _empty_store()
    data.setdefault("version", 1)
    workspaces = []
    for i, raw in enumerate(data.get("workspaces") or []):
        w = _normalize(raw, i)
        if w:
            workspaces.append(w)
    workspaces = _fix_primary(workspaces)
    data["workspaces"] = workspaces
    _mtime_cache = (mtime, data)
    return data


def save_store(data: dict) -> dict:
    global _mtime_cache
    os.makedirs(GLYPH_DIR, exist_ok=True)
    workspaces = []
    for i, raw in enumerate(data.get("workspaces") or []):
        w = _normalize(raw, i)
        if w:
            workspaces.append(w)
    workspaces = _fix_primary(workspaces)
    out: Dict[str, Any] = {"version": 1, "workspaces": workspaces}
    if data.get("seeded"):
        out["seeded"] = True
    tmp = USER_STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, USER_STORE)
    try:
        mtime = os.path.getmtime(USER_STORE)
    except OSError:
        mtime = 0.0
    _mtime_cache = (mtime, out)
    log.log("workspaces_saved", count=len(workspaces))
    return out


def list_workspaces(*, include_missing: bool = True) -> List[dict]:
    store = load_store()
    items = list(store.get("workspaces") or [])
    if not include_missing:
        items = [w for w in items if w.get("exists")]
    return items


def accessible_roots() -> List[str]:
    """Roots für Lesen: enabled, exists, mode != private."""
    roots = []
    seen = set()
    for w in list_workspaces(include_missing=False):
        if not w.get("enabled"):
            continue
        if w.get("mode") == "private":
            continue
        p = w["path"]
        if p in seen:
            continue
        seen.add(p)
        roots.append(p)
    return roots


def primary_root() -> Optional[str]:
    for w in list_workspaces(include_missing=False):
        if w.get("enabled") and w.get("mode") != "private" and w.get("primary"):
            return w["path"]
    roots = accessible_roots()
    return roots[0] if roots else None


def mode_for_root(root: str) -> Optional[str]:
    if not root:
        return None
    try:
        real = os.path.realpath(root)
    except OSError:
        real = root
    for w in list_workspaces(include_missing=True):
        if not w.get("enabled"):
            continue
        if w.get("path") == real:
            return w.get("mode") or "r"
    return None


def mode_for_path(path: str) -> Optional[str]:
    """Mode des Workspace-Roots, der path enthält. None = außerhalb."""
    if path is None or str(path).strip() == "":
        return None
    try:
        cand = os.path.realpath(os.path.expanduser(str(path).strip()))
    except OSError:
        return None
    best = None
    best_len = -1
    for w in list_workspaces(include_missing=False):
        if not w.get("enabled"):
            continue
        root = w["path"]
        if cand == root or cand.startswith(root + os.sep):
            if len(root) > best_len:
                best = w.get("mode") or "r"
                best_len = len(root)
    return best


def workspace_for_path(path: str) -> Optional[dict]:
    if path is None or str(path).strip() == "":
        return None
    try:
        cand = os.path.realpath(os.path.expanduser(str(path).strip()))
    except OSError:
        return None
    best = None
    best_len = -1
    for w in list_workspaces(include_missing=False):
        if not w.get("enabled"):
            continue
        root = w["path"]
        if cand == root or cand.startswith(root + os.sep):
            if len(root) > best_len:
                best = w
                best_len = len(root)
    return best


def get_workspace(wid: str) -> Optional[dict]:
    for w in list_workspaces(include_missing=True):
        if w.get("id") == wid:
            return w
    return None


def parse_attach_input(raw: str) -> dict:
    """Pfad oder Name → {path, name}. Nur existierende Verzeichnisse."""
    s = (raw or "").strip()
    if not s:
        raise ValueError("Pfad fehlt")
    # file:// optional
    if s.startswith("file://"):
        s = s[7:]
    path = os.path.expanduser(s)
    try:
        path = os.path.realpath(path)
    except OSError:
        pass
    if not os.path.isdir(path):
        # Name-only: unter $HOME suchen
        home_cand = os.path.join(_HOME, s)
        if os.path.isdir(home_cand):
            path = os.path.realpath(home_cand)
        else:
            raise ValueError(f"Verzeichnis nicht gefunden: {s}")
    name = os.path.basename(path.rstrip(os.sep)) or path
    return {"path": path, "name": name}


def attach(raw_input: str, mode: str = "r") -> dict:
    parsed = parse_attach_input(raw_input)
    mode = (mode or "r").lower()
    if mode == "r+w":
        mode = "rw"
    if mode not in _MODES:
        mode = "r"
    store = load_store(force=True)
    path = parsed["path"]
    for w in store.get("workspaces") or []:
        try:
            existing = os.path.realpath(w.get("path") or "")
        except OSError:
            existing = w.get("path") or ""
        if existing == path:
            raise ValueError("Workspace bereits angebunden")

    ws = _normalize(
        {
            "id": _slug(parsed["name"]) + "-" + uuid.uuid4().hex[:4],
            "name": parsed["name"],
            "path": path,
            "mode": mode,
            "primary": len(store.get("workspaces") or []) == 0,
            "enabled": True,
        },
        len(store.get("workspaces") or []),
    )
    if not ws:
        raise ValueError("Workspace konnte nicht angelegt werden")
    store.setdefault("workspaces", []).append(ws)
    save_store(store)
    return {"workspace": get_workspace(ws["id"]) or ws}


def detach(wid: str) -> bool:
    store = load_store(force=True)
    before = len(store.get("workspaces") or [])
    store["workspaces"] = [
        w for w in (store.get("workspaces") or []) if w.get("id") != wid
    ]
    if len(store["workspaces"]) == before:
        return False
    save_store(store)
    return True


def update_workspace(wid: str, patch: dict) -> dict:
    store = load_store(force=True)
    found = None
    for w in store.get("workspaces") or []:
        if w.get("id") == wid:
            found = w
            break
    if not found:
        raise ValueError("Workspace nicht gefunden")

    if "mode" in patch:
        m = str(patch["mode"]).lower()
        if m == "r+w":
            m = "rw"
        if m in _MODES:
            found["mode"] = m
    if "enabled" in patch:
        found["enabled"] = bool(patch["enabled"])
    if "name" in patch and str(patch["name"]).strip():
        found["name"] = str(patch["name"]).strip()[:120]
    if patch.get("primary") is True:
        for x in store["workspaces"]:
            x["primary"] = x.get("id") == wid
    if "move" in patch:
        ids = [w["id"] for w in store["workspaces"]]
        i = ids.index(wid)
        j = i - 1 if patch["move"] == "up" else i + 1
        if 0 <= j < len(store["workspaces"]):
            store["workspaces"][i], store["workspaces"][j] = (
                store["workspaces"][j],
                store["workspaces"][i],
            )

    save_store(store)
    item = get_workspace(wid)
    if not item:
        raise ValueError("Workspace nicht gefunden")
    return item


def public_snapshot() -> dict:
    """API/UI — Kabelsalat Workspaces."""
    store = load_store(force=True)
    workspaces = []
    for w in store.get("workspaces") or []:
        ww = dict(w)
        ww["exists"] = os.path.isdir(w["path"])
        workspaces.append(ww)
    return {
        "ok": True,
        "store_path": USER_STORE,
        "workspaces": workspaces,
        "accessible_roots": accessible_roots(),
        "primary_root": primary_root(),
    }
