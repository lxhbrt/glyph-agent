# -*- coding: utf-8 -*-
"""
Minimaler .env-Loader (kein python-dotenv nötig).

Lädt KEY=VALUE-Zeilen aus einer optionalen .env-Datei in os.environ,
überschreibt aber KEINE bereits gesetzten Umgebungsvariablen (die gewinnen).
Verwendung: early in cli.py & allen Einstiegspunkten.
"""
import os


def load_dotenv(path=None):
    if path is None:
        # Standard: .env neben dem Projekt-Root (eine Ebene über core/)
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(os.path.dirname(here), ".env")
    if not os.path.isfile(path):
        return False
    loaded = False
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:  # Umgebung gewinnt
                os.environ[key] = value
                loaded = True
    return loaded
