# -*- coding: utf-8 -*-
"""
Minimaler .env-Loader (kein python-dotenv nötig).

Lädt KEY=VALUE-Zeilen aus einer optionalen .env-Datei in os.environ,
überschreibt aber KEINE bereits gesetzten Umgebungsvariablen (die gewinnen).
Verwendung: early in cli.py & allen Einstiegspunkten.
"""
import json
import os

_BINDING_KEYS = (
    "DIRECT_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENROUTER_API_KEY",
    "XAI_API_KEY",
)
_BINDING_SETTINGS = ("DIRECT_API_URL", "GLYPH_AGENT_URL")


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


def load_ui_bindings(path=None):
    """Füllt leere Env-Slots aus ~/.glyph-ui/bindings.json (Anbindung-Tab)."""
    if path is None:
        path = os.path.join(os.path.expanduser("~"), ".glyph-ui", "bindings.json")
    if not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    keys = data.get("keys") if isinstance(data.get("keys"), dict) else data
    settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    loaded = False
    for kid in _BINDING_KEYS:
        val = ""
        if isinstance(keys, dict):
            val = str(keys.get(kid) or "").strip()
        if not val:
            val = str(data.get(kid) or "").strip()
        if val and not str(os.environ.get(kid) or "").strip():
            os.environ[kid] = val
            loaded = True
    for sid in _BINDING_SETTINGS:
        val = str(settings.get(sid) or data.get(sid) or "").strip()
        if val and not str(os.environ.get(sid) or "").strip():
            os.environ[sid] = val
            loaded = True
    return loaded
