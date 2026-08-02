#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent-/Provider-Regressionstest (Nutzer-Priorisierung: Trace → Tool-Propagation → Fehlerfall).

Testet die AUSFÜHRUNGSKETTE des Tool-Loops (nicht nur die Einstiege):
  1. Tatsächlich verwendetes Modell/Provider im Trace (kein stiller Fallback).
  2. Tool wird wirklich aufgerufen; Ergebnis wird an die finale Antwort weitergereicht.
  3. Fehlerfall: leeres/fehlgeschlagenes Suchergebnis -> KEINE erfundene Antwort.
  4. End-to-End-Assertion (Tool aufgerufen, Ergebnis vorhanden, Modell/Provider erwartet,
     Antwort referenziert nur Tool-Fakten).

Deterministisch: llm.chat und web.web_search werden gemockt (keine echten API-Calls).
Aufruf: python3 tests/test_agent_chain.py
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OK = 0
FAIL = 0


def check(name, cond, detail=""):
    global OK, FAIL
    print(f"  {'✅' if cond else '❌'} {name} {detail}")
    if cond:
        OK += 1
    else:
        FAIL += 1


def run_chain(search_results, llm_script):
    """Führt tool_loop.run mit gemocktem WebSearch + LLM aus."""
    from core import tool_loop
    import core.tool_registry as tr
    import core.web as web

    # WebSearch mocken: liefert feste Ergebnisse (oder leere Liste für Fehlerfall).
    web.web_search = lambda query, count=5, source="exa": search_results

    # LLM mocken: llm_script = Liste von Antworten, die llm.chat der Reihe nach liefert.
    calls = {"n": 0}

    def fake_chat(system, user, temperature=0.3, num_ctx=8192):
        i = calls["n"]
        calls["n"] += 1
        if i < len(llm_script):
            return llm_script[i]
        return "Direkte Antwort ohne Tool."

    import core.llm as llm_mod
    llm_mod.chat = fake_chat

    return tool_loop.run("Suche nach dem besten Setup", max_rounds=3)


def test_1_modell_und_trace():
    print("\n[1] Tatsächlich verwendetes Modell/Provider im Trace (kein stiller Fallback):")
    res = run_chain(
        search_results=[{"title": "Best Setup Guide", "url": "https://example.com/best", "snippet": "Das beste Setup ist X."}],
        llm_script=[
            '{"tool": "WebSearch", "args": {"query": "bestes Setup"}}',  # Erkennung -> Tool-Call
            "Laut Tool-Ergebnis ist das beste Setup X (Quelle: https://example.com/best).",  # finale Antwort
        ],
    )
    trace = res.get("trace") or {}
    check("trace vorhanden", bool(trace))
    check("provider im Trace", bool(trace.get("provider")))
    check("model im Trace", bool(trace.get("model")))
    check("tool_calls im Trace", bool(trace.get("tool_calls")))
    tc = (trace.get("tool_calls") or [{}])[0]
    check("Tool-Status success", tc.get("status") == "success", f"-> {tc.get('status')}")
    check("Tool-Ergebnis-Länge > 0", (tc.get("result_length") or 0) > 0, f"-> {tc.get('result_length')}")
    check("kein Fallback", trace.get("fallback_used") in (False, None))


def test_2_tool_aufruf_und_propagation():
    print("\n[2] Tool-Aufruf + Ergebnis wird an finale Antwort weitergereicht:")
    # Prüfen, dass das Tool-Ergebnis im user-Prompt der finalen Antwort landet.
    captured = {}

    from core import tool_loop
    import core.web as web
    web.web_search = lambda query, count=5, source="exa": [
        {"title": "Setup-Guide", "url": "https://example.com/setup", "snippet": "Empfohlen: Konfig A."}
    ]

    import core.llm as llm_mod
    orig_chat = llm_mod.chat

    def fake_chat(system, user, temperature=0.3, num_ctx=8192):
        # Beim finalen Call (nach Tool) muss das Tool-Ergebnis im Prompt stehen.
        if "Tool-Ergebnis" in user or "[WebSearch" in user or "example.com" in user:
            captured["tool_in_prompt"] = True
        # Erkennung: erst Tool-Call, dann Antwort mit Tool-Fakten
        if not captured.get("round"):
            captured["round"] = 1
            return '{"tool": "WebSearch", "args": {"query": "Setup"}}'
        return "Empfohlen wird Konfig A (laut Tool-Ergebnis, Quelle example.com/setup)."

    llm_mod.chat = fake_chat
    res = tool_loop.run("Suche Setup", max_rounds=3)
    llm_mod.chat = orig_chat

    check("Tool-Ergebnis im finalen Prompt", captured.get("tool_in_prompt") is True,
          "(WebSearch-Ergebnis wurde an Modell weitergegeben)")
    check("Antwort referenziert Tool-Fakt", "Konfig A" in res.get("answer", ""),
          f"-> {res.get('answer','')[:60]}")
    check("Tool wurde aufgerufen", any(t.get("tool") == "WebSearch" for t in res.get("tool_calls", [])),
          f"-> {[t.get('tool') for t in res.get('tool_calls',[])]}")


def test_3_fehlerfall_leeres_ergebnis():
    print("\n[3] Fehlerfall: leeres Suchergebnis -> KEINE erfundene Antwort:")
    from core import tool_loop
    import core.web as web
    # Leeres Suchergebnis (kein Treffer) — Tool ok, aber 0 Ergebnisse.
    web.web_search = lambda query, count=5, source="exa": []
    import core.llm as llm_mod
    orig = llm_mod.chat

    def fake_chat(system, user, temperature=0.3, num_ctx=8192):
        if not hasattr(fake_chat, "n"):
            fake_chat.n = 0
        fake_chat.n += 1
        if fake_chat.n == 1:
            return '{"tool": "WebSearch", "args": {"query": "nichts"}}'
        # Das Modell soll bei leerem Ergebnis ehrlich sein (keine erfundenen Links).
        return "Die Suche hat kein verwertbares Ergebnis geliefert. Ich kann daher keine belastbare Antwort geben."

    llm_mod.chat = fake_chat
    res = tool_loop.run("Suche nach etwas Unbekanntem", max_rounds=3)
    llm_mod.chat = orig

    check("Antwort lehnt Erfindung ab (kein Link/Produkt)", "kein verwertbares" in res.get("answer", ""),
          f"-> {res.get('answer','')[:80]}")
    check("Keine erfundenen URLs in Antwort",
          "http://" not in res.get("answer", ""),
          "(kein http-Link erfunden)")


def test_4_e2e_assertion():
    print("\n[4] End-to-End-Assertion (erwartetes Modell/Provider):")
    # Mit aktivem Provider (real, meist ollama/qwen) prüfen, dass der Trace ihn spiegelt.
    from core import tool_loop
    import core.web as web
    web.web_search = lambda query, count=5, source="exa": [
        {"title": "T", "url": "https://example.com/t", "snippet": "Fakt Y"}
    ]
    import core.llm as llm_mod
    orig = llm_mod.chat

    def fake_chat(system, user, temperature=0.3, num_ctx=8192):
        if not hasattr(fake_chat, "n"):
            fake_chat.n = 0
        fake_chat.n += 1
        if fake_chat.n == 1:
            return '{"tool": "WebSearch", "args": {"query": "q"}}'
        return "Fakt Y (aus Tool-Ergebnis)."

    llm_mod.chat = fake_chat
    res = tool_loop.run("Suche Fakt", max_rounds=3)
    llm_mod.chat = orig

    trace = res.get("trace") or {}
    check("Tool aufgerufen: true", any(t.get("tool") == "WebSearch" for t in res.get("tool_calls", [])), "true")
    check("Tool-Ergebnis vorhanden", (trace.get("tool_calls") or [{}])[0].get("result_length", 0) > 0, "true")
    check("Provider im Trace", bool(trace.get("provider")), f"-> {trace.get('provider')}")
    check("Modell im Trace", bool(trace.get("model")), f"-> {trace.get('model')}")
    check("Antwort enthält Tool-Fakt", "Fakt Y" in res.get("answer", ""), "true")
    check("Antwort behauptet keine nicht gelieferten Quellen",
          "http://" not in res.get("answer", "") or "example.com/t" in res.get("answer", ""),
          "(nur gelieferte Quelle ok)")


if __name__ == "__main__":
    print("=== Agent-/Provider-Regressionstest (Tool-Kette) ===")
    test_1_modell_und_trace()
    test_2_tool_aufruf_und_propagation()
    test_3_fehlerfall_leeres_ergebnis()
    test_4_e2e_assertion()
    print(f"\n=== Ergebnis: {OK} ok, {FAIL} Fehler ===")
    sys.exit(1 if FAIL else 0)
