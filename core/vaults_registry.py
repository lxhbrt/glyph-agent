# -*- coding: utf-8 -*-
"""
Vault-Registry (Kabelsalat-SoT).

Nutzer:   ~/.glyph/vaults.json
Produkt:  ~/.glyph/vaults.defaults.json (leer/minimal, nie Nutzer-Welt überschreiben)

Hot-Reload: load() liest Datei bei jedem Aufruf (mtime-Cache optional kurz).
"""
from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import log

GLYPH_DIR = os.path.expanduser("~/.glyph")
USER_STORE = os.path.join(GLYPH_DIR, "vaults.json")
DEFAULTS_STORE = os.path.join(GLYPH_DIR, "vaults.defaults.json")
OBSIDIAN_ROOT = os.path.expanduser("~/ObsidianVaults")

# Seed nur wenn vaults.json fehlt (bestehende Installation migrieren)
_LEGACY_SEED = [
    {
        "name": "HSEQ Sync",
        "path": os.path.join(OBSIDIAN_ROOT, "HSEQ Sync"),
        "mode": "rw",
        "primary": True,
    },
    {
        "name": "ASI, BS. UWS, QM, EM",
        "path": os.path.join(OBSIDIAN_ROOT, "ASI, BS. UWS, QM, EM"),
        "mode": "r",
        "primary": False,
    },
    {
        "name": "OpenClaw memory-wiki",
        "path": os.path.join(OBSIDIAN_ROOT, "OpenClaw memory-wiki"),
        "mode": "rw",
        "primary": False,
    },
    {
        "name": "Peniel",
        "path": os.path.join(OBSIDIAN_ROOT, "Peniel"),
        "mode": "r",
        "primary": False,
    },
    {
        "name": "Privat",
        "path": os.path.join(OBSIDIAN_ROOT, "Privat"),
        "mode": "private",
        "primary": False,
    },
]

_MODES = frozenset({"r", "rw", "private"})

# Default-Pins (nutzerunabhängig) — relative Pfade im Vault
_DEFAULT_PIN_CANDIDATES = (
    "AGENTS.md",
    "00 MOC - Start.md",
    "00 MOC - Sync Start.md",
    "WIKI.md",
    "index.md",
    "MEMORY.md",
)

_mtime_cache: Tuple[float, Optional[dict]] = (0.0, None)


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (name or "vault").strip().lower()).strip("-")
    return (s or "vault")[:48]


def _empty_store() -> dict:
    return {"version": 1, "vaults": []}


def ensure_defaults_file() -> None:
    os.makedirs(GLYPH_DIR, exist_ok=True)
    if not os.path.isfile(DEFAULTS_STORE):
        with open(DEFAULTS_STORE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "version": 1,
                    "description": "Produkt-Default: leere Vault-Liste. Nutzer-Welt: vaults.json",
                    "vaults": [],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
            f.write("\n")


def _normalize_vault(raw: dict, order: int) -> Optional[dict]:
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
    name = str(raw.get("name") or os.path.basename(path) or "Vault").strip()
    mode = str(raw.get("mode") or "r").strip().lower()
    if mode not in _MODES:
        mode = "r"
    pins_in = raw.get("pins") if isinstance(raw.get("pins"), list) else []
    pins = []
    seen_p = set()
    for p in pins_in:
        if not isinstance(p, dict):
            continue
        rel = str(p.get("path") or "").strip().replace("\\", "/").lstrip("/")
        if not rel or rel in seen_p:
            continue
        seen_p.add(rel)
        pins.append(
            {
                "path": rel,
                "label": str(p.get("label") or os.path.basename(rel)),
                "source": str(p.get("source") or "manual"),
            }
        )
    vid = str(raw.get("id") or "").strip() or _slug(name)
    return {
        "id": vid,
        "name": name[:120],
        "path": path,
        "mode": mode,
        "primary": bool(raw.get("primary")),
        "enabled": raw.get("enabled", True) is not False,
        "pins": pins,
        "order": int(raw.get("order", order)),
        "exists": os.path.isdir(path),
    }


def load_store(*, force: bool = False) -> dict:
    """Lädt Nutzer-SoT; migriert einmalig wenn Datei fehlt."""
    global _mtime_cache
    ensure_defaults_file()
    os.makedirs(GLYPH_DIR, exist_ok=True)

    if not os.path.isfile(USER_STORE):
        store = _migrate_seed()
        save_store(store)
        _mtime_cache = (os.path.getmtime(USER_STORE), store)
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
    vaults = []
    for i, raw in enumerate(data.get("vaults") or []):
        v = _normalize_vault(raw, i)
        if v:
            vaults.append(v)
    # exactly one primary among enabled
    vaults = _fix_primary(vaults)
    data["vaults"] = vaults
    _mtime_cache = (mtime, data)
    return data


def _migrate_seed() -> dict:
    """Bestehende Welt: Legacy-Pfade. Frische Installation ohne Ordner → leere Liste."""
    vaults = []
    any_exist = False
    for i, raw in enumerate(_LEGACY_SEED):
        if os.path.isdir(os.path.expanduser(raw["path"])):
            any_exist = True
        v = _normalize_vault({**raw, "id": _slug(raw["name"]), "pins": []}, i)
        if v and v["exists"]:
            v["pins"] = _auto_pins_for_path(v["path"])
            vaults.append(v)
    if not any_exist:
        return _empty_store()
    vaults = _fix_primary(vaults)
    log.log("vaults_migrated", count=len(vaults))
    return {"version": 1, "vaults": vaults, "migrated_from": "legacy_config"}


def save_store(data: dict) -> dict:
    global _mtime_cache
    os.makedirs(GLYPH_DIR, exist_ok=True)
    vaults = []
    for i, raw in enumerate(data.get("vaults") or []):
        v = _normalize_vault(raw, i)
        if v:
            vaults.append(v)
    vaults = _fix_primary(vaults)
    out = {"version": 1, "vaults": vaults}
    if data.get("migrated_from"):
        out["migrated_from"] = data["migrated_from"]
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
    log.log("vaults_saved", count=len(vaults))
    return out


def _fix_primary(vaults: List[dict]) -> List[dict]:
    enabled = [v for v in vaults if v.get("enabled", True)]
    if not enabled:
        return vaults
    prim = [v for v in enabled if v.get("primary")]
    if len(prim) == 1:
        # keep order but ensure primary first for agent priority
        pid = prim[0]["id"]
        rest = [v for v in vaults if v["id"] != pid]
        head = next(v for v in vaults if v["id"] == pid)
        return [head] + rest
    # none or many → first enabled is primary
    first_id = enabled[0]["id"]
    for v in vaults:
        v["primary"] = v["id"] == first_id
    head = next(v for v in vaults if v["id"] == first_id)
    rest = [v for v in vaults if v["id"] != first_id]
    return [head] + rest


def list_vaults() -> List[dict]:
    return list(load_store().get("vaults") or [])


def get_vault(vid: str) -> Optional[dict]:
    for v in list_vaults():
        if v["id"] == vid:
            return v
    return None


def paths_for_agent() -> List[str]:
    """Enabled vaults, primary first. Private included (read)."""
    out = []
    for v in list_vaults():
        if not v.get("enabled", True):
            continue
        if not v.get("exists") and not os.path.isdir(v["path"]):
            continue
        out.append(v["path"])
    return out


def private_paths() -> List[str]:
    return [
        v["path"]
        for v in list_vaults()
        if v.get("enabled", True) and v.get("mode") == "private"
    ]


def writable_paths() -> List[str]:
    return [
        v["path"]
        for v in list_vaults()
        if v.get("enabled", True) and v.get("mode") == "rw"
    ]


def is_private_path(abs_path: str) -> bool:
    try:
        real = os.path.realpath(abs_path)
    except OSError:
        real = abs_path
    for p in private_paths():
        try:
            root = os.path.realpath(p)
        except OSError:
            root = p
        if real == root or real.startswith(root + os.sep):
            return True
    return False


def is_writable_path(abs_path: str) -> bool:
    try:
        real = os.path.realpath(abs_path)
    except OSError:
        real = abs_path
    for p in writable_paths():
        try:
            root = os.path.realpath(p)
        except OSError:
            root = p
        if real == root or real.startswith(root + os.sep):
            return True
    return False


def apply_to_config() -> List[str]:
    """Schreibt live in config.VAULT_PATHS / VAULT_PATH."""
    from . import config

    paths = paths_for_agent()
    if not paths:
        # Fallback: empty list — agent without vaults
        config.VAULT_PATHS = []
        config.VAULT_PATH = ""
    else:
        config.VAULT_PATHS = paths
        config.VAULT_PATH = paths[0]
    return paths


def parse_attach_input(raw: str) -> dict:
    """
    Pfad | obsidian:// | Vault-Name unter ~/ObsidianVaults/
    → {path, name, pin_file?}
    """
    s = (raw or "").strip()
    if not s:
        raise ValueError("Leere Eingabe")

    pin_file = None
    name = None
    path = None

    if s.startswith("obsidian://"):
        # obsidian://open?vault=HSEQ%20Sync&file=00%20MOC%20-%20Sync%20Start
        u = urlparse(s)
        qs = parse_qs(u.query)
        vault = unquote((qs.get("vault") or [""])[0])
        file_q = unquote((qs.get("file") or [""])[0])
        if not vault:
            raise ValueError("obsidian:// ohne vault=")
        name = vault
        path = os.path.join(OBSIDIAN_ROOT, vault)
        if file_q:
            pin_file = file_q.replace("\\", "/")
            if not pin_file.endswith(".md"):
                pin_file = pin_file + ".md"
    elif os.path.isabs(os.path.expanduser(s)) or s.startswith("~"):
        path = os.path.realpath(os.path.expanduser(s))
        name = os.path.basename(path)
    else:
        # vault name under ObsidianVaults
        name = s
        path = os.path.join(OBSIDIAN_ROOT, s)
        path = os.path.realpath(path)

    if not os.path.isdir(path):
        raise ValueError(f"Ordner nicht gefunden: {path}")

    return {"path": path, "name": name, "pin_file": pin_file}


def _auto_pins_for_path(vault_path: str) -> List[dict]:
    pins = []
    for rel in _DEFAULT_PIN_CANDIDATES:
        full = os.path.join(vault_path, rel)
        if os.path.isfile(full):
            pins.append(
                {
                    "path": rel,
                    "label": os.path.basename(rel),
                    "source": "default",
                }
            )
    return pins


def ensure_default_mds(vault_path: str) -> List[str]:
    """AGENTS.md, 00 MOC - Start.md, MEMORY.md (leer/Sektion) wenn fehlend."""
    created = []
    agents = os.path.join(vault_path, "AGENTS.md")
    if not os.path.isfile(agents):
        with open(agents, "w", encoding="utf-8") as f:
            f.write(
                "# AGENTS.md\n\n"
                "Kurzvertrag für diesen Vault (Glyph °_Agent).\n\n"
                "## Rolle\n"
                "_(Was dieser Vault ist — 2–5 Sätze)_\n\n"
                "## Tabus\n"
                "- Keine erfundenen Fakten\n"
                "- Bei Privat-Modus: kein Cloud-Korpus aus diesem Vault\n"
            )
        created.append("AGENTS.md")

    moc = os.path.join(vault_path, "00 MOC - Start.md")
    if not os.path.isfile(moc):
        # don't overwrite Sync Start if only that exists
        alt = os.path.join(vault_path, "00 MOC - Sync Start.md")
        if not os.path.isfile(alt):
            name = os.path.basename(vault_path)
            with open(moc, "w", encoding="utf-8") as f:
                f.write(
                    f"---\ntags: [moc, start]\ntype: moc\n---\n\n"
                    f"# {name} · Start\n\n"
                    f"Hub für diesen Vault. Links zu wichtigen Notizen hier sammeln.\n\n"
                    f"## Einstiege\n\n- [[AGENTS]]\n- [[MEMORY]]\n"
                )
            created.append("00 MOC - Start.md")

    mem = os.path.join(vault_path, "MEMORY.md")
    if not os.path.isfile(mem):
        with open(mem, "w", encoding="utf-8") as f:
            f.write(
                "# MEMORY (Vault)\n\n"
                "Lokale Langzeit-Notizen **dieses** Vaults.\n"
                "Zentrale Glyph-Memory: `~/.glyph/MEMORY.md` (nicht hier mischen).\n\n"
                "## Notizen\n\n"
            )
        created.append("MEMORY.md")
    return created


def attach(raw_input: str, mode: str = "r") -> dict:
    parsed = parse_attach_input(raw_input)
    mode = (mode or "r").lower()
    if mode not in _MODES:
        mode = "r"
    store = load_store(force=True)
    path = parsed["path"]
    for v in store.get("vaults") or []:
        if os.path.realpath(v.get("path") or "") == path:
            raise ValueError("Vault bereits angebunden")

    created_mds = ensure_default_mds(path)
    pins = _auto_pins_for_path(path)
    if parsed.get("pin_file"):
        rel = parsed["pin_file"]
        if not any(p["path"] == rel for p in pins):
            pins.append({"path": rel, "label": os.path.basename(rel), "source": "manual"})

    vault = _normalize_vault(
        {
            "id": _slug(parsed["name"]) + "-" + uuid.uuid4().hex[:4],
            "name": parsed["name"],
            "path": path,
            "mode": mode,
            "primary": len(store.get("vaults") or []) == 0,
            "pins": pins,
            "enabled": True,
        },
        len(store.get("vaults") or []),
    )
    store.setdefault("vaults", []).append(vault)
    save_store(store)
    apply_to_config()
    return {"vault": vault, "created_mds": created_mds}


def detach(vid: str) -> bool:
    store = load_store(force=True)
    before = len(store.get("vaults") or [])
    store["vaults"] = [v for v in (store.get("vaults") or []) if v.get("id") != vid]
    if len(store["vaults"]) == before:
        return False
    save_store(store)
    apply_to_config()
    return True


def update_vault(vid: str, patch: dict) -> dict:
    store = load_store(force=True)
    found = None
    for v in store.get("vaults") or []:
        if v.get("id") == vid:
            found = v
            break
    if not found:
        raise ValueError("Vault nicht gefunden")

    if "mode" in patch and str(patch["mode"]).lower() in _MODES:
        found["mode"] = str(patch["mode"]).lower()
    if "enabled" in patch:
        found["enabled"] = bool(patch["enabled"])
    if "name" in patch and str(patch["name"]).strip():
        found["name"] = str(patch["name"]).strip()[:120]
    if patch.get("primary") is True:
        for x in store["vaults"]:
            x["primary"] = x.get("id") == vid
    if "pins" in patch and isinstance(patch["pins"], list):
        found["pins"] = patch["pins"]
    if "move" in patch:
        # move: "up" | "down"
        ids = [v["id"] for v in store["vaults"]]
        i = ids.index(vid)
        j = i - 1 if patch["move"] == "up" else i + 1
        if 0 <= j < len(store["vaults"]):
            store["vaults"][i], store["vaults"][j] = store["vaults"][j], store["vaults"][i]

    save_store(store)
    apply_to_config()
    return get_vault(vid)


def add_pin(vid: str, rel_path: str, label: str = "") -> dict:
    rel = (rel_path or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        raise ValueError("pin path fehlt")
    store = load_store(force=True)
    for v in store.get("vaults") or []:
        if v.get("id") != vid:
            continue
        pins = list(v.get("pins") or [])
        if any(p.get("path") == rel for p in pins):
            return v
        pins.append(
            {
                "path": rel,
                "label": label or os.path.basename(rel),
                "source": "manual",
            }
        )
        v["pins"] = pins
        save_store(store)
        return v
    raise ValueError("Vault nicht gefunden")


def remove_pin(vid: str, rel_path: str) -> dict:
    rel = (rel_path or "").strip().replace("\\", "/").lstrip("/")
    store = load_store(force=True)
    for v in store.get("vaults") or []:
        if v.get("id") != vid:
            continue
        v["pins"] = [p for p in (v.get("pins") or []) if p.get("path") != rel]
        save_store(store)
        return v
    raise ValueError("Vault nicht gefunden")


def public_snapshot() -> dict:
    """API/UI."""
    store = load_store(force=True)
    vaults = []
    for v in store.get("vaults") or []:
        vv = dict(v)
        vv["exists"] = os.path.isdir(v["path"])
        vv["obsidian_uri"] = "obsidian://open?vault=" + quote(v["name"])
        vaults.append(vv)
    return {
        "ok": True,
        "store_path": USER_STORE,
        "defaults_path": DEFAULTS_STORE,
        "vaults": vaults,
        "agent_paths": paths_for_agent(),
        "private_paths": private_paths(),
    }
