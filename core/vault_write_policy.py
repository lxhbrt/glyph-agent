# -*- coding: utf-8 -*-
"""
Chat-Wachstum für °_Agent: anlegen und ergänzen, nie löschen.

CreateNote/ApplyEdit nur unter Themen/ und Wiki-Schichten.
Sources nach Anlegen unveränderlich. Eingang, Vorlagen, Fertig, Hauptarchiv,
Privat: nicht aus dem Chat.
"""
from __future__ import annotations

from typing import Callable, Optional

from . import log, vault_tools

GROW_TOOLS = frozenset({"CreateNote", "ApplyEdit", "WikiApply"})

_CREATE_PREFIXES = (
    "Themen/",
    "concepts/",
    "entities/",
    "syntheses/",
    "sources/",
)

_APPLY_PREFIXES = (
    "Themen/",
    "concepts/",
    "entities/",
    "syntheses/",
)

_KNOWN_VAULTS = (
    "HSEQ Sync",
    "memory-wiki",
    "ASI, BS. UWS, QM, EM",
    "Peniel",
    "Privat",
)


def _is_private_ref(path: str) -> bool:
    p = str(path or "").replace("\\", "/").lstrip("/")
    return p == "Privat" or p.startswith("Privat/") or "/Privat/" in f"/{p}"


def _rel(path: str) -> str:
    p = str(path or "").strip().replace("\\", "/")
    if not p:
        return ""
    if vault_tools._is_pending_contract_ref(p):
        return "pending-contract.md"
    p = p.lstrip("/")
    names = []
    try:
        names.extend(vault_tools._bound_vault_names())
    except Exception:
        pass
    for extra in _KNOWN_VAULTS:
        if extra not in names:
            names.append(extra)
    for name in names:
        if p == name:
            return ""
        pref = name + "/"
        if p.startswith(pref):
            p = p[len(pref) :]
            break
    return p


def _under(rel: str, prefixes: tuple[str, ...]) -> bool:
    r = (rel or "").lstrip("/")
    for pref in prefixes:
        if r.startswith(pref) or r == pref.rstrip("/"):
            return True
    return False


def content_ok(tool_name: str, args: Optional[dict]) -> bool:
    args = args or {}
    if tool_name == "CreateNote":
        return bool(str(args.get("content") or "").strip())
    if tool_name in ("ApplyEdit", "WikiApply"):
        return bool(str(args.get("new_content") or "").strip())
    return False


def allow_chat_write(tool_name: str, args: Optional[dict]) -> bool:
    """True = Chat darf ohne Popup schreiben (Wachstum, kein Löschen)."""
    if tool_name not in GROW_TOOLS:
        return False
    args = args if isinstance(args, dict) else {}
    path = str(args.get("path") or "")
    if not path or _is_private_ref(path):
        return False
    if not content_ok(tool_name, args):
        return False
    rel = _rel(path)
    if rel == "pending-contract.md":
        return True
    if tool_name == "CreateNote":
        return _under(rel, _CREATE_PREFIXES)
    return _under(rel, _APPLY_PREFIXES)


def make_chat_confirm() -> Callable[[str, dict], bool]:
    def confirm(tool_name: str, args: dict) -> bool:
        ok = allow_chat_write(tool_name, args)
        log.log(
            "chat_write_confirm",
            tool=tool_name,
            path=str((args or {}).get("path") or "")[:200],
            allowed=ok,
        )
        return ok

    return confirm
