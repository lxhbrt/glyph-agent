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
from . import vault_tools, web, retrieval

# --- Tool-Schema (wird auch dem Modell im System-Prompt beschrieben) ---

# Vault/Recherche-Tools (MODE=agent) — kein Shell, nur Vault-Roots.
TOOLS = [
    {
        "name": "VaultFind",
        "description": (
            "EIN Finde-Werkzeug für den Obsidian-Vault (B+ Hybrid): "
            "0.7 lokale Embeddings (bge-m3) + 0.3 Keyword-Volltext. "
            "NUR Vault-Daten, KEINE Web-Recherche. Bevorzugt dieses Tool für alle Vault-Fragen."
        ),
        "args": {"query": "str", "top_k": "int (optional)", "min_score": "float (optional)"},
        "write": False,
    },
    {
        # Alias → VaultFind (Abwärtskompatibilität)
        "name": "VaultRecall",
        "description": "Alias für VaultFind (Hybrid Embedding+Keyword). Bevorzuge VaultFind.",
        "args": {"query": "str", "top_k": "int (optional)", "min_score": "float (optional)"},
        "write": False,
    },
    {
        # Alias → VaultFind
        "name": "VaultSearch",
        "description": "Alias für VaultFind (Hybrid). Bevorzuge VaultFind.",
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
        "description": (
            "Grobe Web-Recherche (Standard: Exa). NUR anonymisierte Suchbegriffe. "
            "source=tinyfish nur als Zweitquelle. Für konkrete URLs: ExtractUrl/FetchUrl."
        ),
        "args": {"query": "str, anonymisierter Suchbegriff", "count": "int (optional)", "source": "str (optional: 'exa' oder 'tinyfish')"},
        "write": False,
    },
    {
        "name": "ExtractUrl",
        "description": "FEINE Recherche: URL besuchen + strukturierte Daten (TinyFish). NUR öffentliche URLs.",
        "args": {"url": "str", "goal": "str, was extrahiert werden soll (mit JSON-Schema)"},
        "write": False,
    },
    {
        "name": "FetchUrl",
        "description": "FEINE Recherche: öffentlichen URL-Inhalt als Markdown/Text (TinyFish).",
        "args": {"url": "str"},
        "write": False,
    },
    {
        "name": "ObsidianOpen",
        "description": (
            "Optional: öffnet eine Vault-Notiz in der Obsidian-App (kepano-CLI). "
            "Nur Pfade innerhalb erlaubter Vaults. Schreibt nichts."
        ),
        "args": {"path": "str, relativer oder vault-relativer .md-Pfad"},
        "write": False,
    },
]

# CODE-Tools (^_Code / MODE=code) — Workspace-Roots, kein VaultFind.
CODE_TOOLS = [
    {
        "name": "ListDir",
        "description": "Listet Dateien/Ordner relativ zu einem Workspace-Root (nicht rekursiv).",
        "args": {"path": "str (optional, Default '.')"},
        "write": False,
    },
    {
        "name": "ReadFile",
        "description": "Liest eine Datei innerhalb der CODE_WORKSPACE_ROOTS (Text, UTF-8).",
        "args": {"path": "str"},
        "write": False,
    },
    {
        "name": "WriteFile",
        "description": (
            "Schreibt/überschreibt eine Datei (kompletter Inhalt) mit Backup. "
            "Benötigt Glyph-Genehmigung. Kein Löschen."
        ),
        "args": {"path": "str", "content": "str, kompletter neuer Dateiinhalt"},
        "write": True,
    },
    {
        "name": "RunCommand",
        "description": (
            "Führt einen Whitelist-Shell-Befehl im Workspace aus (z.B. git status, "
            "npm test, pytest, ls). Benötigt Glyph-Genehmigung. Kein rm/sudo."
        ),
        "args": {
            "command": "str",
            "cwd": "str (optional, relativ zu Root)",
            "timeout": "int Sekunden optional, max 120",
        },
        "write": True,  # Genehmigungspflicht wie Write
    },
]

TOOL_MAP = {t["name"]: t for t in TOOLS}
CODE_TOOL_MAP = {t["name"]: t for t in CODE_TOOLS}


def tools_for_mode(mode="agent"):
    """Tool-Liste je Betriebsart."""
    m = (mode or "agent").lower()
    if m == "code":
        return CODE_TOOLS
    return TOOLS


def tool_map(mode="agent"):
    m = (mode or "agent").lower()
    if m == "code":
        return CODE_TOOL_MAP
    return TOOL_MAP


def tool_schema_prompt(mode="agent"):
    """Erzeugt die Tool-Beschreibung für den System-Prompt des Modells."""
    lines = ['Verfügbare Werkzeuge (antworte mit JSON {"tool": Name, "args": {...}}):']
    for t in tools_for_mode(mode):
        args = ", ".join(f"{k}:{v}" for k, v in t["args"].items())
        lines.append(f"- {t['name']}({args}) — {t['description']}")
    return "\n".join(lines)


# --- Erkennung & Ausführung ---

def try_parse_tool_call(text):
    """
    Versucht, aus der Modell-Antwort einen Tool-Call zu extrahieren.
    Liefert (tool_name, args) oder None, wenn es keine Tool-Anfrage ist.
    Robust für EINEN oder MEHRERE verschachtelte JSON-Blöcke (gpt-5.6-luna sendet
    teils mehrere WebSearch-Blöcke). Gibt den ERSTEN gültigen Tool-Call zurück.
    Nutzt raw_decode, um verschachtelte Objekte korrekt zu parsen.
    """
    import json
    import re

    s = text.strip()
    # Markdown-Codeblock entfernen, falls die ganze Antwort einer ist
    cm = re.search(r"```(?:json)?\s*(.*?)\s*```", s, re.DOTALL)
    if cm:
        s = cm.group(1)

    decoder = json.JSONDecoder()
    idx = 0
    n = len(s)
    while idx < n:
        c = s[idx]
        if c != "{":
            idx += 1
            continue
        try:
            obj, end = decoder.raw_decode(s, idx)
        except json.JSONDecodeError:
            idx += 1
            continue
        if isinstance(obj, dict) and "tool" in obj:
            name = str(obj.get("tool"))
            args = obj.get("args") or {}
            return (name, args)
        idx = end
    return None


def execute(tool_name, args, confirm=None, mode="agent"):
    """
    Führt ein Tool kontrolliert aus.

    confirm: optionaler Callback confirm(tool_name, args) -> bool.
      Für write=True-Tools wird confirm genau dann aufgerufen; wenn er
      False liefert oder fehlt (und das Tool write=True ist), wird NICHT
      ausgeführt.

    mode: "agent" (Vault) | "code" (^_Code Workspace-Tools)

    Rückgabe: dict {"ok": bool, "result": ..., "error": str|None}
    """
    mode = (mode or "agent").lower()
    tmap = tool_map(mode)
    tool = tmap.get(tool_name)
    if tool is None:
        return {"ok": False, "result": None,
                "error": f"Unbekanntes Tool '{tool_name}'. Erlaubt: {', '.join(tmap)}"}

    # Bestätigung für Schreib-Tools erzwingen
    if tool["write"]:
        if confirm is None:
            return {"ok": False, "result": None,
                    "error": f"Tool '{tool_name}' ist schreibend und benötigt Bestätigung."}
        if not confirm(tool_name, args):
            return {"ok": False, "result": None,
                    "error": "Schreib-Vorgang vom Nutzer abgebrochen."}

    try:
        if mode == "code":
            return _execute_code(tool_name, args or {})
        return _execute_agent(tool_name, args or {})
    except Exception as e:
        return {"ok": False, "result": None, "error": str(e)}


def _execute_agent(tool_name, args):
    if tool_name in ("VaultFind", "VaultRecall", "VaultSearch"):
        q = args.get("query", "")
        top_k = int(args.get("top_k") or args.get("limit") or 4)
        min_score = float(args.get("min_score", 0.35))
        res = retrieval.vault_find(q, top_k=top_k, min_score=min_score)
        return {"ok": True, "result": res}
    if tool_name == "ReadNote":
        res = vault_tools.read_note(args.get("path"))
        return {"ok": True, "result": res}
    if tool_name == "Summarize":
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
        res = web.web_search(
            args.get("query", ""),
            count=int(args.get("count", 5)),
            source=args.get("source", "exa"),
        )
        return {"ok": True, "result": res}
    if tool_name == "ExtractUrl":
        res = web.extract_tinyfish(args.get("url", ""), args.get("goal", ""))
        return {"ok": True, "result": res}
    if tool_name == "FetchUrl":
        res = web.fetch_tinyfish(args.get("url", ""), "markdown")
        return {"ok": True, "result": res}
    if tool_name == "ObsidianOpen":
        res = vault_tools.obsidian_open(args.get("path", ""))
        return {"ok": True, "result": res}
    return {"ok": False, "result": None, "error": f"Tool '{tool_name}' nicht implementiert."}


def _execute_code(tool_name, args):
    from . import code_tools
    if tool_name == "ListDir":
        res = code_tools.list_dir(args.get("path") or ".")
        return {"ok": True, "result": res}
    if tool_name == "ReadFile":
        res = code_tools.read_file(args.get("path"))
        return {"ok": True, "result": res}
    if tool_name == "WriteFile":
        res = code_tools.write_file(args.get("path"), args.get("content", ""))
        return {"ok": True, "result": res}
    if tool_name == "RunCommand":
        timeout = args.get("timeout")
        res = code_tools.run_command(
            args.get("command", ""),
            cwd=args.get("cwd"),
            timeout=int(timeout) if timeout is not None else None,
        )
        # exit_code != 0 ist kein Tool-Fehler — Ergebnis trotzdem ok
        return {"ok": True, "result": res}
    return {"ok": False, "result": None, "error": f"Tool '{tool_name}' nicht implementiert."}
