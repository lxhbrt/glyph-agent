# -*- coding: utf-8 -*-
"""Grant-Store für ^_Code: Einmal / Auftrag / Task.

Workspace-Recht ist nur Capability. Apply braucht einen Grant mit
Root, Pfadpräfixen, Aktionsklassen und Ablauf.
"""
from __future__ import annotations

import os
import secrets
import threading
import time

TASK_IDLE_S = 2 * 3600
ALWAYS_ONCE = frozenset(
    {"package_install", "network", "git_commit", "deploy"}
)
DEFAULT_TASK_CLASSES = ("file_change", "test")

_LOCK = threading.Lock()
_GRANTS = {}  # grant_id -> dict
_ACTIVE_TASK_ID = None
_ACTIVE_AUFTRAG_ID = None


def reset():
    """Tests / Prozess-Reset."""
    global _ACTIVE_TASK_ID, _ACTIVE_AUFTRAG_ID
    with _LOCK:
        _GRANTS.clear()
        _ACTIVE_TASK_ID = None
        _ACTIVE_AUFTRAG_ID = None


def begin_auftrag():
    global _ACTIVE_AUFTRAG_ID
    aid = "auf-" + secrets.token_hex(6)
    with _LOCK:
        # Alter Auftrag-Grant stirbt mit neuem Lauf.
        dead = [
            gid
            for gid, g in _GRANTS.items()
            if g.get("scope") == "auftrag"
        ]
        for gid in dead:
            _GRANTS.pop(gid, None)
        _ACTIVE_AUFTRAG_ID = aid
    return aid


def end_auftrag(auftrag_id=None):
    global _ACTIVE_AUFTRAG_ID
    with _LOCK:
        aid = auftrag_id or _ACTIVE_AUFTRAG_ID
        dead = [
            gid
            for gid, g in _GRANTS.items()
            if g.get("scope") == "auftrag"
            and (not aid or g.get("auftrag_id") == aid)
        ]
        for gid in dead:
            _GRANTS.pop(gid, None)
        if not auftrag_id or auftrag_id == _ACTIVE_AUFTRAG_ID:
            _ACTIVE_AUFTRAG_ID = None


def _norm_rel(rel):
    s = str(rel or "").replace("\\", "/").lstrip("/")
    while s.startswith("./"):
        s = s[2:]
    return s or "."


def _norm_prefix(prefix):
    p = str(prefix or "").replace("\\", "/").strip()
    if p.endswith("/**"):
        p = p[:-3]
    p = p.rstrip("/")
    if p in (".", "", "*", "**"):
        return "."
    return p.lstrip("/")


def path_allowed(prefixes, rel):
    rel = _norm_rel(rel)
    prefs = [_norm_prefix(p) for p in (prefixes or []) if p]
    if not prefs or prefs == ["."]:
        return True
    for p in prefs:
        if p == ".":
            return True
        if rel == p or rel.startswith(p + "/"):
            return True
    return False


def common_prefixes(rel_paths):
    """Pfadpräfixe für einen Änderungssatz: gemeinsamer Ordner, sonst je Parent."""
    rels = [_norm_rel(p) for p in (rel_paths or []) if p]
    if not rels:
        return ["."]
    dirs = []
    for r in rels:
        d = r.rsplit("/", 1)[0] if "/" in r else "."
        dirs.append(d if d else ".")
    if len(set(dirs)) == 1:
        return [dirs[0]]
    parts = [d.split("/") for d in dirs if d != "."]
    if not parts:
        return ["."]
    common = []
    for bits in zip(*parts):
        if len(set(bits)) != 1:
            break
        common.append(bits[0])
    if common:
        return ["/".join(common)]
    uniq = []
    for d in dirs:
        if d not in uniq:
            uniq.append(d)
    return uniq or ["."]


def why_allowed(grant):
    if not grant:
        return ""
    scope = grant.get("scope")
    label = (grant.get("label") or "").strip()
    if scope == "once":
        return "einmal"
    if scope == "auftrag":
        return "Auftrag"
    if scope == "task":
        return f"Task {label}".strip() if label else "Task"
    return scope or ""


def _expired(g, now=None):
    now = now if now is not None else time.time()
    if g.get("revoked") or g.get("consumed"):
        return True
    exp = g.get("expires_at")
    if exp and now >= float(exp):
        return True
    if g.get("scope") == "task":
        last = float(g.get("last_used_at") or g.get("created_at") or 0)
        if last and now - last > TASK_IDLE_S:
            return True
    return False


def _public(g):
    remain = None
    if g.get("scope") == "task":
        last = float(g.get("last_used_at") or g.get("created_at") or 0)
        remain = max(0, int(TASK_IDLE_S - (time.time() - last))) if last else None
    return {
        "grant_id": g.get("grant_id"),
        "scope": g.get("scope"),
        "label": g.get("label") or "",
        "task_id": g.get("task_id"),
        "auftrag_id": g.get("auftrag_id"),
        "workspace_root": g.get("workspace_root") or "",
        "path_prefixes": list(g.get("path_prefixes") or []),
        "action_classes": list(g.get("action_classes") or []),
        "revoked": bool(g.get("revoked")),
        "consumed": bool(g.get("consumed")),
        "idle_remaining_s": remain,
        "why": why_allowed(g),
    }


def public_snapshot():
    now = time.time()
    with _LOCK:
        _sweep(now)
        task = _GRANTS.get(_ACTIVE_TASK_ID) if _ACTIVE_TASK_ID else None
        grants = [_public(g) for g in _GRANTS.values() if not _expired(g, now)]
    return {
        "ok": True,
        "active_task": _public(task) if task and not _expired(task, now) else None,
        "grants": grants,
    }


def _sweep(now=None):
    global _ACTIVE_TASK_ID
    now = now if now is not None else time.time()
    dead = [gid for gid, g in _GRANTS.items() if _expired(g, now)]
    for gid in dead:
        _GRANTS.pop(gid, None)
        if gid == _ACTIVE_TASK_ID:
            _ACTIVE_TASK_ID = None


def issue(
    scope,
    *,
    workspace_root,
    path_prefixes=None,
    action_classes=None,
    label="",
    auftrag_id=None,
    user_message="",
):
    """Neuen Grant anlegen. Task ersetzt den vorherigen aktiven Task."""
    global _ACTIVE_TASK_ID, _ACTIVE_AUFTRAG_ID
    scope = str(scope or "once").strip().lower()
    if scope not in ("once", "auftrag", "task"):
        scope = "once"
    root = os.path.realpath(workspace_root) if workspace_root else ""
    prefixes = list(path_prefixes or ["."])
    classes = list(action_classes or DEFAULT_TASK_CLASSES)
    label = (label or "").strip()
    if not label and user_message:
        label = str(user_message).strip().split("\n", 1)[0][:80]
    gid = "gr-" + secrets.token_hex(6)
    now = time.time()
    rec = {
        "grant_id": gid,
        "scope": scope,
        "label": label,
        "task_id": gid if scope == "task" else None,
        "auftrag_id": auftrag_id or _ACTIVE_AUFTRAG_ID,
        "workspace_root": root,
        "path_prefixes": prefixes,
        "action_classes": classes,
        "created_at": now,
        "last_used_at": now,
        "expires_at": None,
        "revoked": False,
        "consumed": False,
    }
    with _LOCK:
        _sweep(now)
        if scope == "task":
            if _ACTIVE_TASK_ID and _ACTIVE_TASK_ID in _GRANTS:
                _GRANTS[_ACTIVE_TASK_ID]["revoked"] = True
            _ACTIVE_TASK_ID = gid
        _GRANTS[gid] = rec
    return dict(rec)


def matching(root, rel_path, action_class, auftrag_id=None):
    """Passender lebendiger Grant oder None. ALWAYS_ONCE nie."""
    if action_class in ALWAYS_ONCE:
        return None
    root_r = os.path.realpath(root) if root else ""
    now = time.time()
    with _LOCK:
        _sweep(now)
        aid = auftrag_id or _ACTIVE_AUFTRAG_ID
        candidates = []
        for g in _GRANTS.values():
            if _expired(g, now):
                continue
            if g.get("scope") == "auftrag" and aid and g.get("auftrag_id") != aid:
                continue
            if g.get("workspace_root") and root_r and g["workspace_root"] != root_r:
                continue
            classes = g.get("action_classes") or []
            if classes and action_class not in classes:
                continue
            if not path_allowed(g.get("path_prefixes"), rel_path):
                continue
            candidates.append(g)
        if not candidates:
            return None
        # Task vor Auftrag vor Einmal — stehender Scope gewinnt.
        order = {"task": 0, "auftrag": 1, "once": 2}
        candidates.sort(key=lambda g: order.get(g.get("scope"), 9))
        hit = candidates[0]
        hit["last_used_at"] = now
        if hit.get("scope") == "once":
            hit["consumed"] = True
        return dict(hit)


def active_task():
    now = time.time()
    with _LOCK:
        _sweep(now)
        g = _GRANTS.get(_ACTIVE_TASK_ID) if _ACTIVE_TASK_ID else None
        if not g or _expired(g, now):
            return None
        return dict(g)


def outside_task_hint(root, rel_path, action_class):
    """Hinweistext, wenn ein Task aktiv ist und diese Aktion nicht deckt."""
    task = active_task()
    if not task:
        return ""
    if action_class in ALWAYS_ONCE:
        return (
            "Liegt außerhalb des aktiven Tasks "
            f"({task.get('label') or 'Task'}). "
            "Neuen Task starten oder aktuellen abschließen?"
        )
    root_r = os.path.realpath(root) if root else ""
    if task.get("workspace_root") and root_r and task["workspace_root"] != root_r:
        return (
            "Liegt außerhalb des aktiven Tasks. "
            "Neuen Task starten oder aktuellen abschließen?"
        )
    classes = task.get("action_classes") or []
    if classes and action_class not in classes:
        return (
            "Liegt außerhalb des aktiven Tasks. "
            "Neuen Task starten oder aktuellen abschließen?"
        )
    if not path_allowed(task.get("path_prefixes"), rel_path):
        return (
            "Liegt außerhalb des aktiven Tasks. "
            "Neuen Task starten oder aktuellen abschließen?"
        )
    return ""


def revoke(grant_id):
    global _ACTIVE_TASK_ID
    gid = str(grant_id or "")
    with _LOCK:
        g = _GRANTS.get(gid)
        if not g:
            return False
        g["revoked"] = True
        if gid == _ACTIVE_TASK_ID:
            _ACTIVE_TASK_ID = None
        return True


def close_task():
    global _ACTIVE_TASK_ID
    with _LOCK:
        if not _ACTIVE_TASK_ID:
            return False
        g = _GRANTS.get(_ACTIVE_TASK_ID)
        if g:
            g["revoked"] = True
        _ACTIVE_TASK_ID = None
        return True
