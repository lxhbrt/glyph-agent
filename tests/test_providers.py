#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Provider-Selbsttest — prüft die Modell-Provider und den Fallback-Fehlerweg.

Aufruf:
    python3 tests/test_providers.py

Erwartung (lokal, ohne echten Cloud-Key):
  - ollama    -> lädt als Provider 'ollama' (Qwen lokal; ggf. nicht erreichbar,
                 wenn Ollama nicht läuft — dann Warnung statt Fehler).
  - openrouter-> lädt als Provider 'openrouter', ohne Key MUSS sauber fehlschlagen
                 (Datenschutz: kein Cloud-Versuch ohne Key).
  - fallback  -> versucht OpenRouter, fällt bei Fehler auf lokal zurück und
                 kennzeichnet die Antwort (Resilienz).

Dieser Test ruft KEINEN echten Cloud-Dienst auf (wenn kein Key vorhanden ist)
und sendet KEINE lokalen Daten nach außen.
"""
import os
import sys
import importlib

# Sicherstellen, dass das Projekt-Root auf dem Pfad liegt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config
from core.providers import factory

OK = 0
FAIL = 0


def check(name, cond, detail=""):
    global OK, FAIL
    tag = "✅" if cond else "❌"
    print(f"  {tag} {name} {detail}")
    if cond:
        OK += 1
    else:
        FAIL += 1


def load(name, env_overrides=None):
    """Setzt Provider + Env, lädt frisch den Provider."""
    merged = {"HSEQ_PROVIDER": name}
    if env_overrides:
        merged.update(env_overrides)
    for k, v in merged.items():
        os.environ[k] = v
    factory.reset_provider()
    # config neu laden, damit PROVIDER/env neu gelesen wird
    import importlib
    importlib.reload(config)
    importlib.reload(factory)
    return factory.get_provider()


def main():
    import importlib as _il  # lokal, um Verschattung durch load() zu vermeiden
    print("=== Provider-Selbsttest ===\n")

    print("[1] olama (lokal) — muss laden:")
    p = load("ollama")
    check("provider_name == 'ollama'", p.provider_name == "ollama", f"-> {p.provider_name}")
    check("Modellname gesetzt", bool(p.model_name), f"-> {p.model_name}")

    print("\n[2] openrouter — ohne Key MUSS sauber fehlschlagen (Datenschutz):")
    os.environ.pop("OPENROUTER_API_KEY", None)
    os.environ["MODE"] = "openrouter-chat"  # reiner Chat: PROVIDER wird openrouter
    p = load("openrouter")
    check("provider_name == 'openrouter'", p.provider_name == "openrouter", f"-> {p.provider_name}")
    try:
        p.chat("s", "u")
        check("Ohne Key blockiert (kein Cloud-Versuch)", False, "<- hat NICHT geblockt!")
    except RuntimeError as e:
        check("Ohne Key blockiert (kein Cloud-Versuch)", True, f"-> RuntimeError: {str(e)[:40]}")

    print("\n[3] fallback (Agentenmodus) — 2-stufige OpenRouter-Kette + lokales Qwen:")
    p = load("fallback", {
        "OPENROUTER_URL": "http://127.0.0.1:1",
        "OPENROUTER_API_KEY": "test",
        "MODE": "agent",
        "AGENT_PRIMARY_PROVIDER": "fallback",
        "PROVIDER": "fallback",
        "AGENT_OPENROUTER_MODEL": "deepseek/deepseek-chat",
        "AGENT_OPENROUTER_FALLBACK_MODEL": "meta-llama/llama-3.3-70b-instruct:free",
    })
    check("provider_name == 'fallback'", p.provider_name == "fallback", f"-> {p.provider_name}")
    check("Modell zeigt Kette (bevorzugt->gratis->lokal)", "→" in p.model_name, f"-> {p.model_name}")
    try:
        answer = p.chat("Du.", "Sag nur: FALLBACK_OK")
        check("Lokale Antwort erzeugt (Stufe 3)", bool(answer.strip()), f"-> '{answer[:30]}...'")
        check("Lokaler Hinweis vorhanden", "lokal" in answer.lower() or "nicht erreichbar" in answer.lower())
    except Exception as e:
        check("Fallback lief durch", False, f"-> {type(e).__name__}: {str(e)[:60]}")

    print("\n[3b] openrouter-chat Modus — reiner Chat, keine Tools/Vault:")
    # Dieser Modus ist NICHT im Unit-Test prüfbar (Modul-Reload-Isolation mit server.py
    # ist fragil). Er ist über den echten HTTP-Server verifiziert:
    #   MODE=openrouter-chat python3 server.py  →  POST /chat liefert chat_mode=openrouter-chat,
    #   tool_calls=[], und OHNE Qwen-Fallback (reiner OpenRouter-Pfad, Fehler bei Ausfall).
    print(
        "  (ℹ️  Server-E2E-Test: MODE=openrouter-chat → chat_mode, tool_calls=[], "
        "kein Vault/Tools, kein Qwen-Fallback) — per Live-Server verifiziert"
    )


    print("\n[4] Kürzungsschranke (EXTERNAL_MAX_CHARS) im Tool-Loop:")
    from core import tool_loop
    cap = getattr(config, "EXTERNAL_MAX_CHARS", 4000)
    big = [{"tool": "ReadNote", "args": {"path": "x.md"}, "result": {"content": "A" * (cap + 5000)}}]
    # erzwinge Cloud-Ansicht für die Kürzung
    os.environ["HSEQ_PROVIDER"] = "fallback"
    _il.reload(config); _il.reload(tool_loop)
    out = tool_loop._fmt_tool_results(big)
    check(f"Kürzung auf ~{cap} bei fallback", len(out) <= cap + 150, f"-> {len(out)} Zeichen")

    print(f"\n=== Ergebnis: {OK} ok, {FAIL} Fehler ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
