#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Legacy Session-Cleanup (ex OpenClaw 06:00).

Nur sinnvoll solange `openclaw` CLI noch Sessions führt.
Führt aus (wenn Binary da): openclaw sessions cleanup --enforce --all-agents --json
Sonst: skip (ok) — reines Glyph braucht diesen Job nicht.

Kein LLM, kein rm -rf.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")


def find_openclaw() -> str | None:
    for c in (
        "/opt/homebrew/bin/openclaw",
        "/usr/local/bin/openclaw",
        shutil.which("openclaw"),
    ):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def main() -> int:
    day = datetime.now(TZ).strftime("%Y-%m-%d")
    bin_path = find_openclaw()
    if not bin_path:
        print(f"Session-Cleanup {day}: skip — openclaw CLI nicht gefunden (Glyph-only ok)")
        return 0

    cmd = [bin_path, "sessions", "cleanup", "--enforce", "--all-agents", "--json"]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            env={**os.environ, "PATH": "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")},
        )
    except subprocess.TimeoutExpired:
        print(f"Session-Cleanup {day}: Timeout nach 300s")
        return 1
    except OSError as e:
        print(f"Session-Cleanup {day}: Fehler {e}")
        return 1

    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    print(f"Session-Cleanup {day}: exit={r.returncode}")
    if out:
        # compact
        try:
            data = json.loads(out)
            print(json.dumps(data, ensure_ascii=False)[:1200])
        except json.JSONDecodeError:
            print(out[:1200])
    if err and r.returncode != 0:
        print(err[:600])
    # 0 = ok; non-zero still report but don't hard-fail scheduler forever
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
