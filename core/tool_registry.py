# -*- coding: utf-8 -*-
"""
Tool-Registry — deklariert die dem Modell bekannten Werkzeuge + deren
Erkennung/Ausführung. Die eigentliche Logik bleibt in vault_tools/web.py
(unverändert); hier nur die dünne, kontrollierte Zuordnung:

    ToolName (JSON vom Modell)  ->  Python-Aufruf  ->  Ergebnis

Sicherheitsprinzipien:
  - Whitelist: nur diese Tools sind ausführbar (unbekannte -> abgelehnt).
  - Pfad-Sicherheit kommt aus vault_tools (kein ../-Escape).
  - Schreibende Tools sind MARKIERT (write=True) und brauchen im Chat-Flow
    eine Bestätigung, bevor sie ausgeführt werden.
"""
from . import vault_tools, web

# --- Tool-Schema (wird auch dem Modell im System-Prompt beschrieben) ---

TOOLS = [
    {
        "name": "VaultSearch",
        "description": "Durchsucht den Obsidian-Vault nach einem Begriff.",
        "args": {"query": "str", "limit": "int (optional, Default 10)"},
        "write": False,
    },
    {
        "name": "ReadNote",
        "description": "Liest eine Notiz aus dem Vault (relativer Pfad).",
        "args": {"path": "str, z.B. Themen/PSA.md"},
        "write": False,
    },
    {
        "name": "Summarize",
        "description": "Lässt das Modell eine Notiz zusammenfassen/analysieren.",
        "args": {"path": "str, z.B. Themen/PSA.md", "hint": "str (optional)"},
        "write": False,
    },
    {
        "name": "CreateNote",
        "description": "Legt eine NEUE Notiz an (überschreibt nie Bestehendes).",
        "args": {"path": "str", "content": "str"},
        "write": True,
    },
    {
        "name": "ProposeEdit",
        "description": "Erzeugt einen Änderungs-VORSCHLAG (Diff) für eine Notiz. SCHREIBT NOCH NICHTS.",
        "args": {"path": "str", "instruction": "str, was geändert werden soll"},
        "write": False,
    },
    {
        "name": "ApplyEdit",
        "description": "Wendet eine BESTÄTIGTE Änderung an (Backup + Revision). Nur nach Nutzer-Bestätigung.",
        "args": {"path": "str", "new_content": "str, kompletter neuer Inhalt"},
        "write": True,
    },
    {
        "name": "WebSearch",
        "description": "Kontrollierte Web-Recherche (Exa). NUR anonymisierte Suchbegriffe senden.",
        "args": {"query": "str, anonymisierter Suchbegriff", "count": "int (optional)"},
        "write": False,
    },
]

TOOL_MAP = {t["name"]: t for t in TOOLS}


def tool_schema_prompt():
    """Erzeugt die Tool-Beschreibung für den System-Prompt des Modells."""
    lines = ["Verfügbare Werkzeuge (antworte mit JSON {\"tool\": Name, \"args\": {...}}):"]
    for t in TOOLS:
        args = ", ".join(f"{k}:{v}" for k, v in t["args"].items())
        lines.append(f"- {t['name']}({args}) — {t['description']}")
    return "\n".join(lines)


# --- Erkennung & Ausführung ---

def try_parse_tool_call(text):
    """
    Versucht, aus der Modell-Antwort einen Tool-Call zu extrahieren.
    Liefert (tool_name, args) oder None, wenn es keine Tool-Anfrage ist.
    Tolerant gegenüber Markdown-Codeblöcken und führendem/folgendem Text.
    """
    import json
    import re

    s = text.strip()
    # Codeblock entfernen, falls vorhanden
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.DOTALL)
    if m:
        s = m.group(1)
    else:
        # sonst: erstes {...}-Objekt suchen
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if m:
            s = m.group(0)
    try:
        d = json.loads(s)
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or "tool" not in d:
        return None
    name = str(d.get("tool"))
    args = d.get("args") or {}
    return (name, args)


def execute(tool_name, args, confirm=None):
    """
    Führt ein Tool kontrolliert aus.

    confirm: optionaler Callback confirm(tool_name, args) -> bool.
      Für write=True-Tools wird confirm genau dann aufgerufen; wenn er
      False liefert oder fehlt (und das Tool write=True ist), wird NICHT
      ausgeführt. Liefert (ok, result_or_error_message).

    Rückgabe: dict {"ok": bool, "result": ..., "error": str|None}
    """
    tool = TOOL_MAP.get(tool_name)
    if tool is None:
        return {"ok": False, "result": None,
                "error": f"Unbekanntes Tool '{tool_name}'. Erlaubt: {', '.join(TOOL_MAP)}"}

    # Bestätigung für Schreib-Tools erzwingen
    if tool["write"]:
        if confirm is None:
            return {"ok": False, "result": None,
                    "error": f"Tool '{tool_name}' ist schreibend und benötigt Bestätigung."}
        if not confirm(tool_name, args):
            return {"ok": False, "result": None,
                    "error": "Schreib-Vorgang vom Nutzer abgebrochen."}

    try:
        if tool_name == "VaultSearch":
            res = vault_tools.search_vault(args.get("query", ""), limit=int(args.get("limit", 10)))
            return {"ok": True, "result": res}
        if tool_name == "ReadNote":
            res = vault_tools.read_note(args.get("path"))
            return {"ok": True, "result": res}
        if tool_name == "Summarize":
            # Führt die Zusammenfassung über den Agenten aus (LLM liest + fasst zusammen)
            from . import agent as agent_mod
            res = agent_mod.summarize_note(args.get("path"), args.get("hint", ""))
            return {"ok": True, "result": res}
        if tool_name == "CreateNote":
            res = vault_tools.create_note(args.get("path"), args.get("content", ""))
            return {"ok": True, "result": res}
        if tool_name == "ProposeEdit":
            from . import agent as agent_mod
            prop = agent_mod.build_edit_proposal(args.get("path"), args.get("instruction", ""))
            return {"ok": True, "result": prop}
        if tool_name == "ApplyEdit":
            res = vault_tools.apply_edit(args.get("path"), args.get("new_content", ""))
            return {"ok": True, "result": res}
        if tool_name == "WebSearch":
            res = web.search_web(args.get("query", ""), count=int(args.get("count", 5)))
            return {"ok": True, "result": res}
    except Exception as e:
        return {"ok": False, "result": None, "error": str(e)}

    return {"ok": False, "result": None, "error": f"Tool '{tool_name}' nicht implementiert."}
