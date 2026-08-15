# -*- coding: utf-8 -*-
"""
Code-Workspace-Registry (SoT für ^_Code) — Adapter auf bind_store.

Nutzer:   ~/.glyph/workspaces.json
Modes:    r | rw | private  (Vault-Analog)

Hot-Reload: load() liest bei mtime-Änderung neu.
Kabelsalat-UI (Phase 2): attach / detach / update / public_snapshot.
"""
from __future__ import annotations

import os
import uuid
from typing import List, Optional

from . import bind_store, log

GLYPH_DIR = os.path.expanduser("~/.glyph")
USER_STORE = os.path.join(GLYPH_DIR, "workspaces.json")

EXTRA = ()
FLAGS = dict(reorder=False, require_exists=True, home_head="code")

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


def _slug(name: str) -> str:
    return bind_store.slug(name, fallback="ws")


def _seed_store() -> dict:
    workspaces = []
    for i, raw in enumerate(_SEED):
        w = bind_store.normalize_item({**raw}, i, home_head="code")
        if w and w["exists"]:
            workspaces.append(w)
    # Fallback: CODE_WORKSPACE_ROOTS / defaults from config if seed empty
    if not workspaces:
        try:
            from . import config
            for i, p in enumerate(getattr(config, "CODE_WORKSPACE_ROOTS", []) or []):
                w = bind_store.normalize_item(
                    {
                        "path": p,
                        "name": os.path.basename(p) or p,
                        "mode": "rw",
                        "primary": i == 0,
                    },
                    i,
                    home_head="code",
                )
                if w and w["exists"]:
                    workspaces.append(w)
        except Exception:
            pass
    log.log("workspaces_seeded", count=len(workspaces))
    return {"version": 1, "workspaces": workspaces, "seeded": True}


def load_store(*, force: bool = False) -> dict:
    """Lädt Nutzer-SoT; seedet einmalig wenn Datei fehlt."""
    os.makedirs(GLYPH_DIR, exist_ok=True)

    if not os.path.isfile(USER_STORE):
        store = _seed_store()
        return save_store(store)

    store = bind_store.load_store(
        USER_STORE, "workspaces", extra_keys=EXTRA, force=force, **FLAGS
    )
    if bind_store.apply_heads_schema(store, "workspaces", home_head="code"):
        return save_store(store)
    return store


def save_store(data: dict) -> dict:
    extra_meta = {}
    if data.get("seeded"):
        extra_meta["seeded"] = True
    if data.get("heads_schema"):
        extra_meta["heads_schema"] = data["heads_schema"]
    out = bind_store.save_store(
        USER_STORE,
        data,
        "workspaces",
        extra_keys=EXTRA,
        extra_meta=extra_meta or None,
        **FLAGS,
    )
    log.log("workspaces_saved", count=len(out.get("workspaces") or []))
    return out


def list_workspaces(*, include_missing: bool = True) -> List[dict]:
    store = load_store()
    items = list(store.get("workspaces") or [])
    if not include_missing:
        items = [w for w in items if w.get("exists")]
    return items


def _code_mode(item: dict, *, home_head: str) -> str:
    return bind_store.head_mode(item, "code", home_head=home_head)


def accessible_roots() -> List[str]:
    """Roots für Lesen: enabled, exists, an ^_Code gebunden, nicht privat."""
    roots = []
    seen = set()
    for w in list_workspaces(include_missing=False):
        if not w.get("enabled"):
            continue
        if _code_mode(w, home_head="code") not in ("r", "rw"):
            continue
        p = w["path"]
        if p in seen:
            continue
        seen.add(p)
        roots.append(p)
    try:
        from . import vaults_registry as vr

        for v in vr.list_vaults():
            if not v.get("enabled", True):
                continue
            if _code_mode(v, home_head="agent") not in ("r", "rw"):
                continue
            if not v.get("exists") and not os.path.isdir(v["path"]):
                continue
            p = v["path"]
            if p in seen:
                continue
            seen.add(p)
            roots.append(p)
    except Exception:
        pass
    return roots


def primary_root() -> Optional[str]:
    for w in list_workspaces(include_missing=False):
        if (
            w.get("enabled")
            and _code_mode(w, home_head="code") in ("r", "rw")
            and w.get("primary")
        ):
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
            m = _code_mode(w, home_head="code")
            return None if m == "unbound" else m
    try:
        from . import vaults_registry as vr

        for v in vr.list_vaults():
            if not v.get("enabled", True):
                continue
            if v.get("path") == real:
                m = _code_mode(v, home_head="agent")
                return None if m == "unbound" else m
    except Exception:
        pass
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
                m = _code_mode(w, home_head="code")
                if m != "unbound":
                    best = m
                    best_len = len(root)
    try:
        from . import vaults_registry as vr

        for v in vr.list_vaults():
            if not v.get("enabled", True):
                continue
            root = v["path"]
            if cand == root or cand.startswith(root + os.sep):
                if len(root) > best_len:
                    m = _code_mode(v, home_head="agent")
                    if m != "unbound":
                        best = m
                        best_len = len(root)
    except Exception:
        pass
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


def attach(raw_input: str, mode: str = "r", head: Optional[str] = None) -> dict:
    parsed = parse_attach_input(raw_input)
    mode = bind_store.normalize_mode(mode or "r")
    head_id = str(head or "").strip().lower() or None
    if head_id and head_id not in bind_store.HEADS:
        head_id = None
    store = load_store(force=True)
    path = parsed["path"]
    for w in store.get("workspaces") or []:
        try:
            existing = os.path.realpath(w.get("path") or "")
        except OSError:
            existing = w.get("path") or ""
        if existing == path:
            if head_id:
                return {
                    "workspace": update_workspace(
                        w["id"], {"heads": {head_id: mode}}
                    )
                }
            raise ValueError("Workspace bereits angebunden")

    home_mode = mode if (not head_id or head_id == "code") else "unbound"
    heads = bind_store.default_heads(
        "code", home_mode if home_mode != "unbound" else "r"
    )
    if home_mode == "unbound":
        heads["code"] = "unbound"
    if head_id:
        heads[head_id] = mode

    ws = bind_store.normalize_item(
        {
            "id": _slug(parsed["name"]) + "-" + uuid.uuid4().hex[:4],
            "name": parsed["name"],
            "path": path,
            "mode": mode,
            "heads": heads,
            "primary": len(store.get("workspaces") or []) == 0,
            "enabled": True,
        },
        len(store.get("workspaces") or []),
        home_head="code",
    )
    if not ws:
        raise ValueError("Workspace konnte nicht angelegt werden")
    store.setdefault("workspaces", []).append(ws)
    save_store(store)
    return {"workspace": get_workspace(ws["id"]) or ws}


def detach(wid: str) -> bool:
    ok = bind_store.detach_item(
        USER_STORE, "workspaces", wid, extra_keys=EXTRA, **FLAGS
    )
    if ok:
        log.log("workspaces_saved", count=len(list_workspaces()))
    return ok


def update_workspace(wid: str, patch: dict) -> dict:
    bind_store.update_item(
        USER_STORE, "workspaces", wid, patch, extra_keys=EXTRA, **FLAGS
    )
    log.log("workspaces_saved", count=len(list_workspaces()))
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
