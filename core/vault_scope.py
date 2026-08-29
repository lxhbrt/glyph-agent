# -*- coding: utf-8 -*-
"""Welcher Vault in welchem Turn: memory-wiki immer, Arbeits-Vault nur mit Apfel."""
from __future__ import annotations

import os

WIKI_NAME = "memory-wiki"


def is_wiki_root(path) -> bool:
    if not path:
        return False
    base = os.path.basename(os.path.normpath(str(path))).lower()
    if base == WIKI_NAME:
        return True
    p = str(path).replace("\\", "/").lower()
    return f"/{WIKI_NAME}" in f"/{p.strip('/')}" or p.rstrip("/").endswith(WIKI_NAME)


def wiki_roots():
    """Aktive memory-wiki-Pfade aus config.VAULT_PATHS (Registry-Fallback)."""
    from . import config

    paths = list(getattr(config, "VAULT_PATHS", None) or [])
    if not paths:
        try:
            from . import vaults_registry as _vr

            paths = list(_vr.paths_for_agent() or [])
        except Exception:
            paths = []
    out = []
    seen = set()
    for raw in paths:
        if not raw or not is_wiki_root(raw):
            continue
        try:
            real = os.path.realpath(raw)
        except OSError:
            real = str(raw)
        if real in seen:
            continue
        seen.add(real)
        out.append(raw)
    return out


def path_in_roots(path, roots) -> bool:
    """Index-Pfad (/VaultName/rel) oder Abs-Pfad gegen Vault-Roots."""
    if not path or not roots:
        return False
    names = set()
    reals = []
    for raw in roots:
        if not raw:
            continue
        names.add(os.path.basename(os.path.normpath(str(raw))).lower())
        try:
            reals.append(os.path.realpath(raw))
        except OSError:
            reals.append(str(raw))
    p = str(path).replace("\\", "/")
    pl = p.lower().lstrip("/")
    first = pl.split("/", 1)[0]
    if first in names:
        return True
    try:
        if os.path.isabs(p):
            real = os.path.realpath(p)
            for rr in reals:
                marker = rr.rstrip("/\\")
                if real == marker or real.startswith(marker + os.sep) or real.startswith(marker + "/"):
                    return True
    except OSError:
        pass
    return False
