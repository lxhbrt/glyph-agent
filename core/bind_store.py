# -*- coding: utf-8 -*-
"""
Bind-Store: Persistenz + Kern-PATCH für Vaults und Workspaces.

Zwei Projektionen: Runtime (live exists) vs Disk (kein exists).
Kein attach — das bleibt in den Adaptern.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

MODES = frozenset({"r", "rw", "private"})
HEADS = ("grok", "agent", "code")
HEAD_MODES = frozenset({"r", "rw", "private", "unbound"})

# path → (mtime, runtime store)
_mtime_cache: Dict[str, Tuple[float, Optional[dict]]] = {}


def normalize_mode(raw: str) -> str:
    mode = str(raw or "r").strip().lower()
    if mode == "r+w":
        mode = "rw"
    if mode not in MODES:
        return "r"
    return mode


def normalize_head_mode(raw: str, fallback: str = "unbound") -> str:
    mode = str(raw or fallback).strip().lower()
    if mode == "r+w":
        mode = "rw"
    if mode in ("off", "none", "cut", ""):
        mode = "unbound"
    if mode not in HEAD_MODES:
        return fallback if fallback in HEAD_MODES else "unbound"
    return mode


def default_heads(home_head: str, mode: str) -> Dict[str, str]:
    """Grok starts open (rw). Others: only the home head. Privat stays privat."""
    home = home_head if home_head in HEADS else "agent"
    m = normalize_mode(mode)
    grok = "private" if m == "private" else "rw"
    return {
        "grok": grok if home != "grok" else m,
        "agent": m if home == "agent" else "unbound",
        "code": m if home == "code" else "unbound",
    }


def normalize_heads(raw, *, home_head: str, mode: str) -> Dict[str, str]:
    base = default_heads(home_head, mode)
    if not isinstance(raw, dict):
        return base
    out = dict(base)
    for h in HEADS:
        if h in raw:
            out[h] = normalize_head_mode(raw[h], fallback=base[h])
    return out


def head_mode(item: Optional[dict], head: str, *, home_head: str = "agent") -> str:
    if not isinstance(item, dict):
        return "unbound"
    heads = item.get("heads")
    if isinstance(heads, dict) and head in heads:
        return normalize_head_mode(heads.get(head), fallback="unbound")
    if head == home_head:
        return normalize_mode(item.get("mode") or "r")
    if head == "grok":
        return "private" if normalize_mode(item.get("mode") or "r") == "private" else "rw"
    return "unbound"


def upgrade_grok_open(items: List[dict], *, home_head: str) -> bool:
    """Old default left grok unbound. Open it unless the folder is privat."""
    changed = False
    home = home_head if home_head in HEADS else "agent"
    for it in items:
        heads = dict(it.get("heads") or {})
        if heads.get("grok") != "unbound":
            continue
        home_m = heads.get(home) or it.get("mode") or "r"
        heads["grok"] = "private" if home_m == "private" else "rw"
        it["heads"] = heads
        changed = True
    return changed


def apply_heads_schema(store: dict, list_key: str, *, home_head: str) -> bool:
    """Return True if the caller should persist (schema bump and/or grok open)."""
    if int(store.get("heads_schema") or 1) >= 2:
        return False
    upgrade_grok_open(list(store.get(list_key) or []), home_head=home_head)
    store["heads_schema"] = 2
    return True


def slug(name: str, fallback: str = "item") -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (name or fallback).strip().lower()).strip("-")
    return (s or fallback)[:48]


def _safe_order(value, fallback: int) -> int:
    try:
        if value is None:
            return int(fallback)
        return int(value)
    except (TypeError, ValueError):
        return int(fallback)


def normalize_item(
    raw: dict,
    order: int,
    *,
    extra_keys: tuple = (),
    home_head: str = "agent",
) -> Optional[dict]:
    """Kernfelder + Extras; hängt immer live exists an (Runtime)."""
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
    name = str(raw.get("name") or os.path.basename(path) or "Bind").strip()
    vid = str(raw.get("id") or "").strip() or slug(name)
    home = home_head if home_head in HEADS else "agent"
    mode = normalize_mode(raw.get("mode") or "r")
    heads = normalize_heads(raw.get("heads"), home_head=home, mode=mode)
    home_mode = heads.get(home)
    if home_mode and home_mode != "unbound":
        mode = home_mode
    item: Dict[str, Any] = {
        "id": vid,
        "name": name[:120],
        "path": path,
        "mode": mode,
        "heads": heads,
        "primary": bool(raw.get("primary")),
        "enabled": raw.get("enabled", True) is not False,
        "order": _safe_order(raw.get("order", order), order),
        "exists": os.path.isdir(path),
    }
    for k in extra_keys:
        if k in raw:
            item[k] = raw[k]
    return item


def to_disk(item: dict, *, extra_keys: tuple = (), home_head: str = "agent") -> dict:
    """Disk-Record: kein exists, kein obsidian_uri."""
    out: Dict[str, Any] = {
        "id": item.get("id"),
        "name": item.get("name"),
        "path": item.get("path"),
        "mode": normalize_mode(item.get("mode") or "r"),
        "heads": normalize_heads(
            item.get("heads"),
            home_head=home_head if home_head in HEADS else "agent",
            mode=item.get("mode") or "r",
        ),
        "primary": bool(item.get("primary")),
        "enabled": item.get("enabled", True) is not False,
        "order": _safe_order(item.get("order", 0), 0),
    }
    for k in extra_keys:
        if k in item:
            out[k] = item[k]
    return out


def fix_primary(items: list, *, reorder: bool, require_exists: bool) -> list:
    """Genau ein Primary unter Eligible, wenn Eligible nicht leer ist.

    Eligible = enabled and (not require_exists or exists).
    0 Eligible → no-op (Flags + Reihenfolge).
    """
    eligible = [
        it
        for it in items
        if it.get("enabled") and (not require_exists or it.get("exists"))
    ]
    if not eligible:
        return items

    primaries = [it for it in eligible if it.get("primary")]
    if len(primaries) == 1:
        winner = primaries[0]
    else:
        winner = eligible[0]
        wid = winner["id"]
        for it in items:
            it["primary"] = it.get("id") == wid

    if not reorder:
        return items
    pid = winner["id"]
    head = next(it for it in items if it.get("id") == pid)
    rest = [it for it in items if it.get("id") != pid]
    return [head] + rest


def _empty(list_key: str) -> dict:
    return {"version": 1, list_key: []}


def _meta_from(data: dict, list_key: str) -> dict:
    return {k: data[k] for k in data if k not in ("version", list_key)}


def _not_found(list_key: str) -> ValueError:
    if list_key == "vaults":
        return ValueError("Vault nicht gefunden")
    if list_key == "workspaces":
        return ValueError("Workspace nicht gefunden")
    return ValueError("nicht gefunden")


def load_store(
    user_store: str,
    list_key: str,
    *,
    extra_keys: tuple = (),
    reorder: bool,
    require_exists: bool,
    force: bool = False,
    home_head: str = "agent",
) -> dict:
    """Cache-Hit → Runtime-Dict. File-Read → normalize + fix_primary."""
    if not os.path.isfile(user_store):
        return _empty(list_key)

    try:
        mtime = os.path.getmtime(user_store)
    except OSError:
        mtime = 0.0
    cached = _mtime_cache.get(user_store)
    if not force and cached is not None and cached[0] == mtime and cached[1] is not None:
        return cached[1]

    try:
        with open(user_store, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = _empty(list_key)
    if not isinstance(data, dict):
        data = _empty(list_key)
    data.setdefault("version", 1)
    items: List[dict] = []
    for i, raw in enumerate(data.get(list_key) or []):
        try:
            item = normalize_item(
                raw, i, extra_keys=extra_keys, home_head=home_head
            )
        except Exception:
            continue
        if item:
            items.append(item)
    data[list_key] = fix_primary(
        items, reorder=reorder, require_exists=require_exists
    )
    _mtime_cache[user_store] = (mtime, data)
    return data


def save_store(
    user_store: str,
    data: dict,
    list_key: str,
    *,
    extra_keys: tuple = (),
    extra_meta: Optional[dict] = None,
    reorder: bool,
    require_exists: bool,
    home_head: str = "agent",
) -> dict:
    """Schreibt Disk-Projektion; cached und returned Runtime (exists live)."""
    os.makedirs(os.path.dirname(os.path.abspath(user_store)) or ".", exist_ok=True)
    items: List[dict] = []
    for i, raw in enumerate(data.get(list_key) or []):
        try:
            item = normalize_item(
                raw, i, extra_keys=extra_keys, home_head=home_head
            )
        except Exception:
            continue
        if item:
            items.append(item)
    items = fix_primary(items, reorder=reorder, require_exists=require_exists)

    meta = dict(extra_meta or {})
    runtime: Dict[str, Any] = {"version": 1, list_key: items, **meta}
    disk: Dict[str, Any] = {
        "version": 1,
        list_key: [
            to_disk(it, extra_keys=extra_keys, home_head=home_head) for it in items
        ],
        **meta,
    }

    tmp = user_store + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(disk, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, user_store)
    try:
        mtime = os.path.getmtime(user_store)
    except OSError:
        mtime = 0.0
    _mtime_cache[user_store] = (mtime, runtime)
    return runtime


def update_item(
    user_store: str,
    list_key: str,
    vid: str,
    patch: dict,
    *,
    extra_keys: tuple = (),
    reorder: bool,
    require_exists: bool,
    home_head: str = "agent",
) -> dict:
    """Nur mode|heads|enabled|name|primary|move. Unbekannte Keys (inkl. pins) ignorieren."""
    store = load_store(
        user_store,
        list_key,
        extra_keys=extra_keys,
        reorder=reorder,
        require_exists=require_exists,
        force=True,
        home_head=home_head,
    )
    items = store.get(list_key) or []
    found = None
    for it in items:
        if it.get("id") == vid:
            found = it
            break
    if not found:
        raise _not_found(list_key)

    home = home_head if home_head in HEADS else "agent"
    patch = patch or {}
    if "mode" in patch:
        found["mode"] = normalize_mode(patch["mode"])
        merged = dict(found.get("heads") or {})
        merged[home] = found["mode"]
        found["heads"] = normalize_heads(
            merged, home_head=home, mode=found["mode"]
        )
    if "heads" in patch and isinstance(patch["heads"], dict):
        merged = {**(found.get("heads") or {}), **patch["heads"]}
        found["heads"] = normalize_heads(
            merged, home_head=home, mode=found.get("mode") or "r"
        )
        home_mode = found["heads"].get(home)
        if home_mode and home_mode != "unbound":
            found["mode"] = home_mode
    if "enabled" in patch:
        found["enabled"] = bool(patch["enabled"])
    if "name" in patch and str(patch["name"]).strip():
        found["name"] = str(patch["name"]).strip()[:120]
    if patch.get("primary") is True:
        for it in items:
            it["primary"] = it.get("id") == vid
    if "move" in patch:
        ids = [it["id"] for it in items]
        i = ids.index(vid)
        j = i - 1 if patch["move"] == "up" else i + 1
        if 0 <= j < len(items):
            items[i], items[j] = items[j], items[i]

    saved = save_store(
        user_store,
        store,
        list_key,
        extra_keys=extra_keys,
        extra_meta=_meta_from(store, list_key) or None,
        reorder=reorder,
        require_exists=require_exists,
        home_head=home,
    )
    for it in saved.get(list_key) or []:
        if it.get("id") == vid:
            return it
    raise _not_found(list_key)


def detach_item(
    user_store: str,
    list_key: str,
    vid: str,
    *,
    extra_keys: tuple = (),
    reorder: bool,
    require_exists: bool,
    home_head: str = "agent",
) -> bool:
    store = load_store(
        user_store,
        list_key,
        extra_keys=extra_keys,
        reorder=reorder,
        require_exists=require_exists,
        force=True,
        home_head=home_head,
    )
    before = len(store.get(list_key) or [])
    store[list_key] = [it for it in (store.get(list_key) or []) if it.get("id") != vid]
    if len(store[list_key]) == before:
        return False
    save_store(
        user_store,
        store,
        list_key,
        extra_keys=extra_keys,
        extra_meta=_meta_from(store, list_key) or None,
        reorder=reorder,
        require_exists=require_exists,
        home_head=home_head,
    )
    return True
