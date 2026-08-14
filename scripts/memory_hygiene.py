#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Glyph Memory-Hygiene (ex OpenClaw 03:00 Datenschutz+Memory-Check).

Deterministisch, kein LLM — robust gegen Timeouts.
  1) Tagesdatei ~/.glyph/memory/YYYY-MM-DD.md anlegen falls fehlt
  2) ~/.glyph/MEMORY.md auf grobe PII scannen (optional anonymisieren mit --fix)
  3) Kurzreport stdout

Exit 0 immer bei erfolgreicher Prüfung (auch wenn PII gefunden und nur gemeldet).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")
GLYPH = os.path.expanduser("~/.glyph")
MEMORY = os.path.join(GLYPH, "MEMORY.md")
MEM_DIR = os.path.join(GLYPH, "memory")

# Grob: E-Mail, DE-Telefon, lange Zahlenketten (IBAN-ish) — keine KI-Halluzination
_RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_RE_PHONE = re.compile(
    r"(?<!\d)(?:\+49|0049|0)\s*[\d\s\-/\(\)]{8,18}\d"
)
_RE_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")

# Whitelist-Fragmente die in MEMORY absichtlich stehen dürfen
_ALLOW = (
    "alexander hubert",
    "+4915118567252",  # eigenes WA aus alter Config — nicht auto-redact
)


def _today() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


def ensure_daily(day: str) -> dict:
    os.makedirs(MEM_DIR, exist_ok=True)
    path = os.path.join(MEM_DIR, f"{day}.md")
    if os.path.isfile(path):
        return {"path": path, "created": False}
    body = (
        f"# {day}\n\n"
        f"<!-- auto: memory_hygiene {datetime.now(TZ).isoformat(timespec='seconds')} -->\n\n"
        f"## Notizen\n\n"
        f"_(Tageslog — optional ergänzen)_\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return {"path": path, "created": True}


def scan_pii(text: str) -> list:
    hits = []
    low = text.lower()
    for m in _RE_EMAIL.finditer(text):
        val = m.group(0)
        if any(a in val.lower() for a in _ALLOW):
            continue
        hits.append({"kind": "email", "value": val, "span": m.span()})
    for m in _RE_PHONE.finditer(text):
        val = re.sub(r"\s+", " ", m.group(0)).strip()
        compact = re.sub(r"\D", "", val)
        if any(re.sub(r"\D", "", a) in compact for a in _ALLOW if any(c.isdigit() for c in a)):
            continue
        hits.append({"kind": "phone", "value": val, "span": m.span()})
    for m in _RE_IBAN.finditer(text):
        hits.append({"kind": "iban-like", "value": m.group(0), "span": m.span()})
    return hits


def redact(text: str, hits: list) -> str:
    # reverse order so spans stay valid
    out = text
    for h in sorted(hits, key=lambda x: x["span"][0], reverse=True):
        a, b = h["span"]
        placeholder = f"[{h['kind'].upper()}]"
        out = out[:a] + placeholder + out[b:]
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Glyph memory hygiene")
    p.add_argument("--fix", action="store_true", help="PII in MEMORY.md ersetzen")
    p.add_argument("--json", action="store_true", help="JSON-Report")
    args = p.parse_args(argv)

    day = _today()
    daily = ensure_daily(day)
    mem_exists = os.path.isfile(MEMORY)
    hits = []
    fixed = False
    if mem_exists:
        with open(MEMORY, encoding="utf-8", errors="replace") as f:
            body = f.read()
        hits = scan_pii(body)
        if hits and args.fix:
            new_body = redact(body, hits)
            if new_body != body:
                bak = MEMORY + f".bak-pii-{day}"
                with open(bak, "w", encoding="utf-8") as f:
                    f.write(body)
                with open(MEMORY, "w", encoding="utf-8") as f:
                    f.write(new_body)
                fixed = True

    report = {
        "ok": True,
        "day": day,
        "daily": daily,
        "memory_path": MEMORY,
        "memory_exists": mem_exists,
        "pii_hits": len(hits),
        "pii_kinds": sorted({h["kind"] for h in hits}),
        "redacted": fixed,
        "samples": [h["kind"] + ":" + h["value"][:40] for h in hits[:5]],
    }

    # human short (WhatsApp-tauglich falls jemals angehängt)
    lines = [
        f"Memory-Hygiene {day}",
        f"Daily: {'neu' if daily.get('created') else 'ok'} ({os.path.basename(daily['path'])})",
        f"MEMORY PII: {len(hits)}" + (" → redacted" if fixed else (" → clean" if not hits else " (gemeldet, nicht gefixt)")),
    ]
    if hits and not fixed:
        lines.append("Hinweis: python3 scripts/memory_hygiene.py --fix")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("\n".join(lines))
        if hits:
            for s in report["samples"]:
                print(f"  - {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
