#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
glyph-agent — einfache lokale Oberfläche (Kommandozeile).

Persönlicher Assistent für den Obsidian-Vault. Läuft komplett lokal
über Ollama (Qwen). Keine OpenClaw-, keine Netzwerk-Abhängigkeit außer der
bewusst kontrollierten Web-Recherche (siehe Such-Unterbefehl).

Verwendung:
  python3 -m scripts.cli search "Altöl"
  python3 -m scripts.cli read "Themen/PSA.md"
  python3 -m scripts.cli summarize "Themen/PSA.md" ["Zusatzauftrag"]
  python3 -m scripts.cli propose "Themen/PSA.md" "Füge Abschnitt Prüfintervalle ein"
  python3 -m scripts.cli create "test/Neue Notiz.md" "Hallo"
  python3 -m scripts.cli backups
  python3 -m scripts.cli web "Aktuelle TRGS 510 Anforderungen"
"""
import os
import sys

# Projektwurzel auf den Import-Pfad legen
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config, vault_tools, agent
from core import dotenv

dotenv.load_dotenv()  # optionale .env laden (EXA_API_KEY etc.), Umgebung gewinnt

USAGE = __doc__


def cmd_search(args):
    if not args:
        print(USAGE)
        return
    query = " ".join(args)
    res = agent.search(query)
    print(f"\n=== Suchergebnis für '{query}' ===\n")
    for h in res["hits"][:10]:
        print(f"  [{h['hits']} Treffer] {h['path']}")
    print("\n=== Einordnung durch das Modell ===\n")
    print(res["reasoning"])


def cmd_read(args):
    if not args:
        print(USAGE)
        return
    path = args[0]
    try:
        note = vault_tools.read_note(path)
        print(f"\n=== {note['path']} ({note['chars']} Zeichen) ===\n")
        print(note["content"])
    except Exception as e:
        print(f"Fehler: {e}")


def cmd_summarize(args):
    if not args:
        print(USAGE)
        return
    path = args[0]
    hint = " ".join(args[1:]) if len(args) > 1 else ""
    try:
        res = agent.summarize_note(path, hint)
        print(f"\n=== Zusammenfassung: {res['path']} ===\n")
        print(res["summary"])
    except Exception as e:
        print(f"Fehler: {e}")


def cmd_create(args):
    if len(args) < 2:
        print("Verwendung: create <Pfad> <Inhalt>")
        return
    path = args[0]
    content = " ".join(args[1:])
    try:
        res = vault_tools.create_note(path, content)
        if res["created"]:
            print(f"✅ Notiz erstellt: {res['path']}")
        else:
            print(f"⚠️ Existiert bereits, nichts überschrieben: {res['path']}")
    except Exception as e:
        print(f"Fehler: {e}")


def cmd_propose(args):
    """Erzeugt einen Änderungsvorschlag (Diff) OHNE zu schreiben, fragt dann nach."""
    if len(args) < 2:
        print("Verwendung: propose <Pfad> <Änderungs-Anweisung>")
        return
    path = args[0]
    instruction = " ".join(args[1:])
    try:
        prop = agent.build_edit_proposal(path, instruction)
        print(f"\n=== Änderungsvorschlag für {prop['path']} ===\n")
        print(prop["diff"])
        if not prop["changed"]:
            print("\n(Keine inhaltliche Änderung — Inhalt blieb gleich.)")
            return
        answer = input("\nÜbernehmen? [j/N] ").strip().lower()
        if answer in ("j", "ja", "y", "yes"):
            res = agent.confirm_edit(prop["path"], prop["new_content"])
            if res.get("applied"):
                print(f"✅ Änderung übernommen (Revision R{res['rev']}). Backup: {res['backup']}")
            else:
                print("ℹ️ Keine Änderung (Inhalt identisch).")
        else:
            print("Abgebrochen — nichts geschrieben.")
    except Exception as e:
        print(f"Fehler: {e}")


def cmd_backups(_args):
    backups = vault_tools.list_backups()
    if not backups:
        print("Noch keine Backups vorhanden.")
    else:
        print("\n=== Revisions-Backups ===\n")
        for b in backups:
            print(f"  {b}")


def cmd_web(args):
    """Kontrollierte Web-Recherche: zeigt Suchanfrage vor, ruft dann Exa auf.
    (Ausbaustufe — markiert, was an den Webdienst geht, sendet keine privaten
    Dokumentinhalte ungefiltert.)"""
    if not args:
        print("Verwendung: web <Suchbegriff, anonymisiert>")
        return
    query = " ".join(args)
    print(f"Suchanfrage, die an den Webdienst geht: '{query}'")
    print("(Vergewissere dich, dass keine internen/privaten Inhalte enthalten sind.)")
    try:
        from core.web import search_web
        results = search_web(query, count=5)
        print("\n=== Suchergebnisse ===\n")
        for i, r in enumerate(results, 1):
            print(f"{i}. {r.get('title','')}\n   {r.get('url','')}\n   {r.get('snippet','')}\n")
    except ImportError:
        print("Web-Recherche-Modul noch nicht implementiert (core/web.py fehlt).")
    except Exception as e:
        print(f"Web-Fehler: {e}")


def main(argv):
    if not argv:
        print(USAGE)
        return
    cmd, rest = argv[0], argv[1:]
    table = {
        "search": cmd_search,
        "read": cmd_read,
        "summarize": cmd_summarize,
        "create": cmd_create,
        "propose": cmd_propose,
        "backups": cmd_backups,
        "web": cmd_web,
        "help": lambda _a: print(USAGE),
        "--help": lambda _a: print(USAGE),
        "-h": lambda _a: print(USAGE),
    }
    fn = table.get(cmd)
    if not fn:
        print(f"Unbekannter Befehl: {cmd}\n")
        print(USAGE)
        return
    fn(rest)


if __name__ == "__main__":
    config.ensure_dirs()
    main(sys.argv[1:])
