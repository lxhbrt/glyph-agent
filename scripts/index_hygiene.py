#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Index-Hygiene: prüft Wiki-Sources und Vault-Index auf heikle Treffer
(Privat, Passwörter, Behörden-Kopien, blocked-Namen).

Schreibt Bericht nach logs/index_hygiene_report.json (kein Löschen).
Aufruf: python3 scripts/index_hygiene.py
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import config  # noqa: E402

# Muster, die im Wiki/Index heikel sind (Lektion OpenClaw unsafe-local)
HEIKLE_PATTERNS = [
    r"privat",
    r"passwort",
    r"password",
    r"geheim",
    r"personenbezogen",
    r"secrets?",
    r"health",
    r"behörden-recht",
    r"behoerden-recht",
    r"familie-",
    r"unterhalt",
    r"jugendamt",
    r"recovery",
    r"_recovery",
]

WIKI = None
for v in getattr(config, "VAULT_PATHS", []):
    if "memory-wiki" in v or "OpenClaw" in v:
        WIKI = v
        break


def _matches(path: str):
    low = path.lower()
    hits = [p for p in HEIKLE_PATTERNS if re.search(p, low)]
    return hits


def scan_wiki_sources():
    out = []
    if not WIKI or not os.path.isdir(WIKI):
        return out
    sources = os.path.join(WIKI, "sources")
    if not os.path.isdir(sources):
        return out
    for root, _dirs, files in os.walk(sources):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, WIKI)
            m = _matches(rel)
            if m:
                out.append({"path": rel, "patterns": m, "size": os.path.getsize(full)})
    return out


def scan_index():
    idx_path = os.path.join(ROOT, "logs", "vault_index.json")
    out = []
    if not os.path.isfile(idx_path):
        return out, 0
    with open(idx_path, encoding="utf-8") as f:
        data = json.load(f)
    docs = data.get("docs") or []
    seen = set()
    for d in docs:
        p = d.get("path") or ""
        if p in seen:
            continue
        m = _matches(p)
        if m:
            seen.add(p)
            out.append({"path": p, "patterns": m})
    return out, len({d.get("path") for d in docs})


def main():
    wiki_hits = scan_wiki_sources()
    index_hits, index_paths = scan_index()
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "wiki_root": WIKI,
        "wiki_heikle_sources": len(wiki_hits),
        "index_unique_paths": index_paths,
        "index_heikle_paths": len(index_hits),
        "blocked_dirs": list(getattr(config, "BLOCKED_DIRS", []) or []),
        "wiki_samples": wiki_hits[:40],
        "index_samples": index_hits[:40],
        "recommendation": (
            "Heikle Wiki-Sources manuell prüfen/löschen (OpenClaw-Ingest). "
            "Privat-Vault nicht in VAULT_PATHS. Nach Bereinigung: "
            "python3 -c 'from core.retrieval import build_index_from_vault; print(build_index_from_vault(quiet=True))'"
        ),
    }
    out_path = os.path.join(ROOT, "logs", "index_hygiene_report.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("=== Index-Hygiene ===")
    print(f"Wiki heikle Sources: {report['wiki_heikle_sources']}")
    print(f"Index heikle Pfade:  {report['index_heikle_paths']} (von {index_paths} unique)")
    print(f"Bericht: {out_path}")
    if wiki_hits[:8]:
        print("Beispiele Wiki:")
        for h in wiki_hits[:8]:
            print(f"  - {h['path']}  ({', '.join(h['patterns'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
