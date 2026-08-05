#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent-/Provider-Regressionstest (Nutzer-Priorisierung: Trace → Tool-Propagation → Fehlerfall).

Testet die AUSFÜHRUNGSKETTE des Tool-Loops (nicht nur die Einstiege):
  1. Tatsächlich verwendetes Modell/Provider im Trace (kein stiller Fallback).
  2. Tool wird wirklich aufgerufen; Ergebnis wird an die finale Antwort weitergereicht.
  3. Fehlerfall: leeres/fehlgeschlagenes Suchergebnis -> KEINE erfundene Antwort.
  4. End-to-End-Assertion.
  5. Tool-Call-Erkennung bei mehreren/verschachtelten JSON-Blöcken (gpt-5.6-luna-Stil).

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
    """Führt tool_loop.run mit gemocktem WebSearch + LLM + leerem Vault (Precheck) aus.
    Der Vault-Precheck liefert hier einen LEEREN Vault (status=empty), damit WebSearch
    die relevante Recherche-Quelle ist und der deterministische Precheck need_web setzt."""
    from core import tool_loop
    import core.web as web
    import core.llm as llm_mod
    import core.retrieval as retrieval_mod

    web.web_search = lambda query, count=5, source="exa": search_results
    # Precheck-Vault: leer -> WebSearch wird nachgezogen (gewolltes Routing-Verhalten).
    def _empty_vault(query, top_k=None, min_score=None, **kw):
        return {
            "status": "empty", "query": query, "candidates": 0, "selected": 0,
            "threshold": 0.6, "sources": [], "results": [],
        }
    retrieval_mod.vault_find = _empty_vault
    retrieval_mod.search = _empty_vault
    calls = {"n": 0}

    def fake_chat(system, user, temperature=0.3, num_ctx=8192):
        i = calls["n"]
        calls["n"] += 1
        if i < len(llm_script):
            return llm_script[i]
        return "Direkte Antwort ohne Tool."

    llm_mod.chat = fake_chat
    return tool_loop.run("Suche nach dem besten Setup", max_rounds=3)


def web_tc(tool_calls):
    """Liefert den WebSearch-Eintrag aus tool_calls (nach dem VaultRecall-Precheck)."""
    return next((t for t in tool_calls if t.get("tool") == "WebSearch"), {})


def test_1_modell_und_trace():
    print("\n[1] Tatsächlich verwendetes Modell/Provider im Trace (kein stiller Fallback):")
    res = run_chain(
        search_results=[{"title": "Best Setup Guide", "url": "https://example.com/best", "snippet": "Das beste Setup ist X."}],
        llm_script=[
            '{"tool": "WebSearch", "args": {"query": "bestes Setup"}}',
            "Laut Tool-Ergebnis ist das beste Setup X (Quelle: https://example.com/best).",
        ],
    )
    trace = res.get("trace") or {}
    check("trace vorhanden", bool(trace))
    check("provider im Trace", bool(trace.get("provider")))
    check("model im Trace", bool(trace.get("model")))
    check("tool_calls im Trace", bool(trace.get("tool_calls")))
    ws = web_tc(trace.get("tool_calls") or [])
    check("WebSearch-Tool-Status success", ws.get("status") == "success", f"-> {ws.get('status')}")
    check("WebSearch-Ergebnis-Länge > 0", (ws.get("result_length") or 0) > 0, f"-> {ws.get('result_length')}")
    check("kein Fallback", trace.get("fallback_used") in (False, None))


def test_2_tool_aufruf_und_propagation():
    print("\n[2] Tool-Aufruf + Ergebnis wird an finale Antwort weitergereicht:")
    captured = {}
    from core import tool_loop
    import core.web as web
    import core.llm as llm_mod
    import core.retrieval as retrieval_mod

    web.web_search = lambda query, count=5, source="exa": [
        {"title": "Setup-Guide", "url": "https://example.com/setup", "snippet": "Empfohlen: Konfig A."}
    ]
    def _empty_vault(query, top_k=None, min_score=None, **kw):
        return {
            "status": "empty", "query": query, "candidates": 0, "selected": 0,
            "threshold": 0.6, "sources": [], "results": [],
        }
    retrieval_mod.vault_find = _empty_vault
    _orig_retr = retrieval_mod.search
    retrieval_mod.search = lambda query, top_k=None, min_score=None: {
        "status": "empty", "query": query, "candidates": 0, "selected": 0,
        "threshold": 0.6, "sources": [], "results": [],
    }
    orig_chat = llm_mod.chat

    def fake_chat(system, user, temperature=0.3, num_ctx=8192):
        if "Tool-Ergebnis" in user or "[WebSearch" in user or "example.com" in user:
            captured["tool_in_prompt"] = True
        if not captured.get("round"):
            captured["round"] = 1
            return '{"tool": "WebSearch", "args": {"query": "Setup"}}'
        return "Empfohlen wird Konfig A (laut Tool-Ergebnis, Quelle example.com/setup)."

    llm_mod.chat = fake_chat
    res = tool_loop.run("Suche Setup", max_rounds=3)
    llm_mod.chat = orig_chat
    retrieval_mod.search = _orig_retr

    check("Tool-Ergebnis im finalen Prompt", captured.get("tool_in_prompt") is True)
    check("Antwort referenziert Tool-Fakt", "Konfig A" in res.get("answer", ""), f"-> {res.get('answer','')[:60]}")
    check("Tool wurde aufgerufen", any(t.get("tool") == "WebSearch" for t in res.get("tool_calls", [])),
          f"-> {[t.get('tool') for t in res.get('tool_calls',[])]}")


def test_3_fehlerfall_leeres_ergebnis():
    print("\n[3] Fehlerfall: leeres Suchergebnis -> KEINE erfundene Antwort:")
    from core import tool_loop
    import core.web as web
    import core.llm as llm_mod
    import core.retrieval as retrieval_mod

    web.web_search = lambda query, count=5, source="exa": []
    def _empty_vault(query, top_k=None, min_score=None, **kw):
        return {
            "status": "empty", "query": query, "candidates": 0, "selected": 0,
            "threshold": 0.6, "sources": [], "results": [],
        }
    retrieval_mod.vault_find = _empty_vault
    _orig_retr = retrieval_mod.search
    retrieval_mod.search = _empty_vault
    orig = llm_mod.chat

    def fake_chat(system, user, temperature=0.3, num_ctx=8192):
        if not hasattr(fake_chat, "n"):
            fake_chat.n = 0
        fake_chat.n += 1
        if fake_chat.n == 1:
            return '{"tool": "WebSearch", "args": {"query": "nichts"}}'
        return "Die Suche hat kein verwertbares Ergebnis geliefert. Ich kann daher keine belastbare Antwort geben."

    llm_mod.chat = fake_chat
    res = tool_loop.run("Suche nach etwas Unbekanntem", max_rounds=3)
    llm_mod.chat = orig
    retrieval_mod.search = _orig_retr

    check("Antwort lehnt Erfindung ab", "kein verwertbares" in res.get("answer", ""), f"-> {res.get('answer','')[:80]}")
    check("Keine erfundenen URLs", "http://" not in res.get("answer", ""))


def test_4_e2e_assertion():
    print("\n[4] End-to-End-Assertion (erwartetes Modell/Provider):")
    from core import tool_loop
    import core.web as web
    import core.llm as llm_mod
    import core.retrieval as retrieval_mod

    web.web_search = lambda query, count=5, source="exa": [
        {"title": "T", "url": "https://example.com/t", "snippet": "Fakt Y"}
    ]
    # Vault-Precheck: leer -> WebSearch relevant (Routing-Verhalten).
    def _empty_vault(query, top_k=None, min_score=None, **kw):
        return {
            "status": "empty", "query": query, "candidates": 0, "selected": 0,
            "threshold": 0.6, "sources": [], "results": [],
        }
    retrieval_mod.vault_find = _empty_vault
    _orig_retr = retrieval_mod.search
    retrieval_mod.search = _empty_vault
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
    retrieval_mod.search = _orig_retr

    trace = res.get("trace") or {}
    check("Tool aufgerufen", any(t.get("tool") == "WebSearch" for t in res.get("tool_calls", [])), "true")
    check("Tool-Ergebnis vorhanden", (web_tc((trace.get("tool_calls") or [])).get("result_length") or 0) > 0, "true")
    check("Provider im Trace", bool(trace.get("provider")), f"-> {trace.get('provider')}")
    check("Modell im Trace", bool(trace.get("model")), f"-> {trace.get('model')}")
    check("Antwort enthält Tool-Fakt", "Fakt Y" in res.get("answer", ""), "true")
    check("Antwort behauptet keine nicht gelieferten Quellen",
          "http://" not in res.get("answer", "") or "example.com/t" in res.get("answer", ""))


def test_5_tool_call_erkennung():
    print("\n[5] Tool-Call-Erkennung (mehrere/verschachtelte Blöcke, gpt-5.6-luna-Stil):")
    from core import tool_registry as tr
    multi = '{"tool":"WebSearch","args":{"query":"A","count":3}}\n\n{"tool":"WebSearch","args":{"query":"B"}}'
    r = tr.try_parse_tool_call(multi)
    check("mehrere Blöcke -> erster Tool-Call", r is not None and r[0] == "WebSearch", f"-> {r}")
    cb = '```json\n{"tool": "ReadNote", "args": {"path": "x.md"}}\n```'
    r2 = tr.try_parse_tool_call(cb)
    check("Codeblock -> Tool-Call", r2 is not None and r2[0] == "ReadNote", f"-> {r2}")
    prosa = 'Ich suche. {"tool":"WebSearch","args":{"query":"test"}}'
    r3 = tr.try_parse_tool_call(prosa)
    check("Prosa umschlossen -> Tool-Call", r3 is not None and r3[0] == "WebSearch", f"-> {r3}")
    check("kein Tool -> None", tr.try_parse_tool_call("Ich antworte normal.") is None)


if __name__ == "__main__":
    print("=== Agent-/Provider-Regressionstest (Tool-Kette) ===")
    test_1_modell_und_trace()
    test_2_tool_aufruf_und_propagation()
    test_3_fehlerfall_leeres_ergebnis()
    test_4_e2e_assertion()
    test_5_tool_call_erkennung()
    print(f"\n=== Ergebnis: {OK} ok, {FAIL} Fehler ===")
    sys.exit(1 if FAIL else 0)
