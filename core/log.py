# -*- coding: utf-8 -*-
"""
Einfaches Aktions-Protokoll (JSON-Lines).

Jede Aktion des Agenten (lesen, suchen, erstellen, ändern) wird hier
mit Zeitstempel + Kontext geloggt. Kein Framework — reine stdlib.
"""
import json
import os
import time

from . import config


def log(action, **context):
    """Fügt einen Protokolleintrag hinzu. Wirft bei Fehlern nicht."""
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "action": action,
        **context,
    }
    try:
        config.ensure_dirs()
        with open(config.LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:  # Protokoll nie tödlich werden lassen
        print(f"[log-warn] {e}")


def read_recent(limit=50):
    """Liest die letzten Einträge zurück (für Übersicht/Debug)."""
    if not os.path.exists(config.LOG_FILE):
        return []
    entries = []
    with open(config.LOG_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries[-limit:]
