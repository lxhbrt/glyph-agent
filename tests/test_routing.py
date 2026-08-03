#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Routing-Tests — deterministische Entscheidung "Doku, Internet oder beides".

Szenarien (Nutzer-Priorisierung):
  1. Vault-Treffer ausreichend  -> nur internal, kein Web
  2. Vault leer/unsicher        -> Web nachgezogen (beide Quellen)
  3. aktuelle Frage             -> Web direkt (classify_intent current)
  4. beide Quellen              -> internal_sources + external_sources getrennt
  5. kein stiller/falsch dargestellter Fallback (fallback_used nur bei local-Qwen)

Getestet werden core.routing (pure Funktionen) sowie die Trace-Ableitung
sources.vault / sources.web aus tool_loop._build_sources_trace.
Deterministisch, keine echten API/LLM-Calls.
Aufruf: python3 tests/test_routing.py
"""
import os
import sys

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


def run_loop_with(user_message, vault, web_results, llm_script, current=False):
    """Führt tool_loop.run mit vollständig gemockten Quellen + LLM aus.
    vault: retrieval.search()-Ergebnis (dict) zum Mocken des Precheck-Such.
    web_results: Liste von WebSearch-Treffern."""
    from core import tool_loop
    import core.web as web
    import core.llm as llm_mod
    import core.retrieval as retrieval_mod

    retrieval_mod.search = lambda query, top_k=None, min_score=None: vault
    web.web_search = lambda query, count=5, source="exa": web_results
    calls = {"n": 0}

    def fake_chat(system, user, temperature=0.3, num_ctx=8192):
        i = calls["n"]
        calls["n"] += 1
        if i < len(llm_script):
            return llm_script[i]
        return "Direkte Antwort ohne Tool."

    llm_mod.chat = fake_chat
    return tool_loop.run(user_message, max_rounds=3)


def test_1_vault_ausreichend():
    print("\n[1] Vault-Treffer ausreichend -> nur internal, kein Web (Intent domain):")
    vault = {
        "status": "success", "query": "Brandschutz", "candidates": 4, "selected": 2,
        "threshold": 0.6, "sources": ["/wiki/Brandschutz.md"], "top_k": 4,
        "results": [{"path": "/wiki/Brandschutz.md", "score": 0.88}],
    }
    res = run_loop_with(
        "Was gilt für Brandschutz im Betrieb?",
        vault=vault,
        web_results=[{"title": "Norm", "url": "https://x/n", "snippet": "n"}],
        llm_script=["Antwort aus Doku: Brandschutzregeln (Quelle /wiki/Brandschutz.md)."],
    )
    trace = res.get("trace") or {}
    # Routing musste VaultRecall als Precheck gesetzt haben; WebSearch darf NICHT laufen,
    # da Vault ausreichend + domain.
    check("VaultRecall im Precheck", any(t.get("tool") == "VaultRecall" for t in res.get("tool_calls", [])), "true")
    check("kein WebSearch (ausreichend)", not any(t.get("tool") == "WebSearch" for t in res.get("tool_calls", [])), "true")
    check("sources.vault.count >= 1", (trace.get("sources") or {}).get("vault", {}).get("count", 0) >= 1, "true")
    # web-Block nur, wenn WebSearch lief -> hier NICHT vorhanden
    check("sources hat keinen web-Block", "web" not in (trace.get("sources") or {}), "true")
    # finaler Prompt enthält internal_sources
    cap = {}
    # Wir prüfen den gesetzten retrieval-Trace
    rv = trace.get("retrieval") or {}
    check("retrieval-Trace: vault", rv.get("type") == "vault" and rv.get("selected", 0) >= 1, f"-> {rv.get('type')}/{rv.get('selected')}")


def test_2_vault_leer_web_gezogen():
    print("\n[2] Vault leer/unzureichend -> WebSearch nachgezogen (beide Quellen):")
    vault_empty = {
        "status": "empty", "query": "xyz", "candidates": 0, "selected": 0,
        "threshold": 0.6, "sources": [], "results": [],
    }
    res = run_loop_with(
        "Informationen über Feuerlöscher",
        vault=vault_empty,
        web_results=[{"title": "Feuerlöscher-Guide", "url": "https://x/f", "snippet": "ABC-Pulver"}],
        llm_script=[
            '{"tool": "WebSearch", "args": {"query": "Feuerlöscher Pflichten"}}',
            "Externe Quelle: ABC-Pulver (https://x/f).",
        ],
    )
    trace = res.get("trace") or {}
    check("VaultRecall-Precheck lief", any(t.get("tool") == "VaultRecall" for t in res.get("tool_calls", [])), "true")
    check("WebSearch nachgezogen", any(t.get("tool") == "WebSearch" for t in res.get("tool_calls", [])), "true")
    srcs = trace.get("sources") or {}
    check("sources.vault.empty", srcs.get("vault", {}).get("status") == "empty", f"-> {srcs.get('vault',{}).get('status')}")
    check("sources.web vorhanden", "web" in srcs, "true")
    check("sources.web.count >= 1", (srcs.get("web") or {}).get("count", 0) >= 1, "true")


def test_3_aktuelle_frage_web_direkt():
    print("\n[3] Aktuelle Frage ('heutige Normen') -> classify_intent == current (Web direkt):")
    from core import routing
    check("classify current: 'heutige Normen'", routing.classify_intent("Was sind die heutigen Normen?") == "current", "true")
    check("classify current: 'aktuelle Vorschriften'", routing.classify_intent("aktuelle Vorschriften") == "current", "true")
    check("classify current: '2026'", routing.classify_intent("Regeln 2026") == "current", "true")
    check("classify domain: 'Feuerlöscher'", routing.classify_intent("Feuerlöscher") == "domain", "true")
    check("classify domain: 'Brandschutz'", routing.classify_intent("Brandschutz") == "domain", "true")

    # Aktuelle Frage + genügend Vault -> Web darf trotzdem dazukommen (current)
    vault_ok = {"status": "success", "query": "q", "candidates": 3, "selected": 1,
                "threshold": 0.6, "sources": ["/wiki/A.md"], "results": [{"path": "/wiki/A.md", "score": 0.7}]}
    res = run_loop_with(
        "Welche Normen gelten heute für PSA?",
        vault=vault_ok,
        web_results=[{"title": "PSA-Norm", "url": "https://x/psa", "snippet": "EN 388"}],
        llm_script=[
            '{"tool": "WebSearch", "args": {"query": "PSA Normen"}}',
            "Doku + Web: EN 388 (https://x/psa).",
        ],
    )
    srcs = (res.get("trace") or {}).get("sources") or {}
    # current -> Vault UND Web dürfen vorhanden sein (parallele Nutzung erlaubt)
    check("current: Vault im Trace", "vault" in srcs, "true")
    check("current: Web im Trace erlaubt", srcs.get("web", {}).get("count", 0) >= 1, "true")


def test_4_beide_quellen_getrennt():
    print("\n[4] Beide Quellen -> internal_sources/external_sources im finalen Prompt getrennt:")
    from core import tool_loop
    vault = {"status": "success", "query": "brand", "candidates": 1, "selected": 1,
             "threshold": 0.6, "sources": ["/wiki/B.md"], "results": [{"path": "/wiki/B.md", "score": 0.8}]}
    res = run_loop_with(
        "Brandschutz aktuell",
        vault=vault,
        web_results=[{"title": "W", "url": "https://x/w", "snippet": "neu"}],
        llm_script=[
            '{"tool": "WebSearch", "args": {"query": "Brandschutz aktuell"}}',
            "Antwort.",
        ],
    )
    # _fmt_tool_results muss internal_sources + external_sources trennen
    import core.web as web
    import core.retrieval as retrieval_mod
    trs = [
        {"tool": "VaultRecall", "args": {"query": "q"}, "result": {"status": "success", "selected": 1,
             "sources": ["/wiki/B.md"], "results": [{"path": "/wiki/B.md", "score": 0.8}]}},
        {"tool": "WebSearch", "args": {"query": "q2"}, "result": {"sources": [{"url": "https://x/w"}]}},
    ]
    body = tool_loop._fmt_tool_results(trs)
    check("internal_sources im Prompt", "internal_sources:" in body, "true")
    check("external_sources im Prompt", "external_sources:" in body, "true")


def test_5_fallback_sichtbar():
    print("\n[5] fallback_used: nur bei bewusstem lokalem Qwen-Fallback sichtbar:")
    from core import tool_loop, llm

    class Fake:
        def __init__(self, pname, last_used=None):
            self.provider_name = pname
            self.model_name = "m"
            self.last_used = last_used

    orig = llm.get_provider

    def with_provider(fake):
        llm.get_provider = lambda: fake
        try:
            return tool_loop._build_trace([], [], None)
        finally:
            llm.get_provider = orig

    t_local = with_provider(Fake("fallback", "local"))
    check("local-Qwen-Fallback -> fallback_used true", t_local.get("fallback_used") is True, "true")
    t_free = with_provider(Fake("fallback", "openrouter:free"))
    check("openrouter:free -> fallback_used false", t_free.get("fallback_used") is False, "true")
    t_plain = with_provider(Fake("ollama"))
    check("ollama -> fallback_used false", t_plain.get("fallback_used") is False, "true")


def main():
    print("=== Routing-Selbsttest ===")
    test_1_vault_ausreichend()
    test_2_vault_leer_web_gezogen()
    test_3_aktuelle_frage_web_direkt()
    test_4_beide_quellen_getrennt()
    test_5_fallback_sichtbar()
    print(f"\n=== Ergebnis: {OK} ok, {FAIL} Fehler ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
