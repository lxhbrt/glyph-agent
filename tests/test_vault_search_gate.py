#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ordner-Suche: aus = memory-wiki; an = Arbeits-Vault + gewählte Treffer + Wiki."""
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


def _empty_vault(query, top_k=None, min_score=None, **kw):
    return {
        "status": "empty",
        "query": query,
        "candidates": 0,
        "selected": 0,
        "threshold": 0.6,
        "sources": [],
        "results": [],
    }


def _run(user_message, **kwargs):
    from core import tool_loop
    import core.llm as llm_mod
    import core.retrieval as retrieval_mod
    import core.web as web

    script = kwargs.pop("_script", None) or ["Direkt ohne Vault."]
    calls = {"vault": 0, "n": 0}

    def vault_find(query, top_k=None, min_score=None, **kw):
        calls["vault"] += 1
        calls.setdefault("roots", []).append(kw.get("roots"))
        return _empty_vault(query)

    retrieval_mod.vault_find = vault_find
    retrieval_mod.search = vault_find
    web.web_search = lambda query, count=5, source="exa": []

    def fake_chat(system, user, temperature=0.3, num_ctx=8192):
        i = calls["n"]
        calls["n"] += 1
        if i < len(script):
            return script[i]
        return "Direkt ohne Vault."

    llm_mod.chat = fake_chat
    res = tool_loop.run(user_message, max_rounds=3, **kwargs)
    return res, calls


def test_off_searches_wiki_only():
    print("\n[1] vault_search=False → memory-wiki VaultFind:")
    res, calls = _run("Was gilt für Brandschutz?", vault_search=False)
    tools = [t.get("tool") for t in res.get("tool_calls") or []]
    check("vault_find aufgerufen", calls["vault"] >= 1, f"n={calls['vault']}")
    check("VaultFind im Trace", "VaultFind" in tools, f"-> {tools}")
    check("Antwort ok", bool(res.get("ok")), str(res.get("ok")))
    roots_args = [r for r in calls.get("roots") or [] if r is not None]
    check("Wiki-Roots gesetzt", len(roots_args) >= 1, f"-> {roots_args[:2]}")


def test_default_still_searches():
    print("\n[2] Default (Jobs/compat) → VaultFind läuft:")
    res, calls = _run("Was gilt für Brandschutz?")
    tools = [t.get("tool") for t in res.get("tool_calls") or []]
    check("vault_find aufgerufen", calls["vault"] >= 1, f"n={calls['vault']}")
    check("VaultFind im Trace", "VaultFind" in tools, f"-> {tools}")


def test_selected_only():
    print("\n[3] vault_selected → nur gewählte Treffer, kein neuer VaultFind:")
    selected = [
        {
            "id": "file:/HSEQ Sync/PSA.md",
            "kind": "file",
            "path": "/HSEQ Sync/PSA.md",
            "title": "PSA.md",
            "excerpt": "PSA ist Pflicht im Produktionsbereich.",
            "score": 0.9,
        }
    ]
    res, calls = _run(
        "Was gilt für PSA?",
        vault_search=True,
        vault_selected=selected,
    )
    tools = [t.get("tool") for t in res.get("tool_calls") or []]
    check("wiki overlay vault_find", calls["vault"] >= 1, f"n={calls['vault']}")
    check("VaultFind-Eintrag (gewählt)", "VaultFind" in tools, f"-> {tools}")
    srcs = ((res.get("trace") or {}).get("sources") or {}).get("vault") or {}
    check("sources.vault.count == 1", srcs.get("count") == 1, f"-> {srcs}")


def test_selected_pdf_is_read():
    print("\n[3b] gewählte PDF → ReadPdf-Text im Kontext:")
    from core import tool_loop, pdf_tools

    old = pdf_tools.read_pdf
    pdf_tools.read_pdf = lambda path, max_chars=None: {
        "ok": True,
        "path": path,
        "content": "Krane: UVV und Befaehigung.",
        "chars": 28,
        "truncated": False,
        "engine": "pdftotext",
        "error": None,
    }
    try:
        out = tool_loop._selected_vault_outcome(
            [
                {
                    "kind": "file",
                    "path": "/ASI, BS. UWS, QM, EM/Arbeitssicherheit/Vorlagen/016_Krane.pdf",
                    "title": "016_Krane.pdf",
                    "excerpt": "",
                }
            ],
            "Was ist in einem KFZ Betrieb zu Krane zu beachten?",
        )
    finally:
        pdf_tools.read_pdf = old
    hist = out.get("history_append") or ""
    tools = [c.get("tool") for c in out.get("tool_calls") or []]
    check("PDF-Text im Kontext", "UVV und Befaehigung" in hist, hist[:240])
    check("ReadPdf im Trace", "ReadPdf" in tools, str(tools))
    check("kein brew", "brew" not in hist.lower() and "poppler" not in hist.lower(), hist[:120])


def test_llm_vaultfind_wiki_only():
    print("\n[4] Toggle aus + LLM VaultFind → memory-wiki, nicht blocken:")
    res, calls = _run(
        "Such im Vault nach PSA",
        vault_search=False,
        _script=[
            '{"tool": "VaultFind", "args": {"query": "PSA"}}',
            "Wiki-Kontext reicht.",
        ],
    )
    blocked = [
        t
        for t in (res.get("tool_calls") or [])
        if t.get("tool") == "VaultFind" and t.get("ok") is False
    ]
    check("VaultFind nicht abgelehnt", len(blocked) == 0, f"-> {res.get('tool_calls')}")
    check("vault_find gelaufen", calls["vault"] >= 1, f"n={calls['vault']}")


_LIVE_DSML = (
    "<\uff5c\uff5cDSML\uff5c\uff5ctool_calls>\n"
    '<\uff5c\uff5cDSML\uff5c\uff5cinvoke name="VaultFind">\n'
    '<\uff5c\uff5cDSML\uff5c\uff5cparameter name="query" string="true">'
    "Kranbetrieb Kranführer Hebezeug Lastaufnahmemittel KFZ Werkstatt Prüfung"
    "</\uff5c\uff5cDSML\uff5c\uff5cparameter>\n"
    "</\uff5c\uff5cDSML\uff5c\uff5cinvoke>\n"
    "</\uff5c\uff5cDSML\uff5c\uff5ctool_calls>"
)

_WEBSEARCH_DSML = (
    "<\uff5c\uff5cDSML\uff5c\uff5ctool_calls>\n"
    '<\uff5c\uff5cDSML\uff5c\uff5cinvoke name="WebSearch">\n'
    '<\uff5c\uff5cDSML\uff5c\uff5cparameter name="query" string="true">'
    "Kranbetrieb KFZ Werkstatt Anforderungen DGUV BetrSichV"
    "</\uff5c\uff5cDSML\uff5c\uff5cparameter>\n"
    "</\uff5c\uff5cDSML\uff5c\uff5cinvoke>\n"
    "</\uff5c\uff5cDSML\uff5c\uff5ctool_calls>"
)


def test_blocked_vaultfind_does_not_leak_dsml():
    print("\n[5] Toggle aus + DSML-VaultFind: Markup nicht als Antwort, Loop darf WebSearch:")
    res, calls = _run(
        "was muss ich in einem KFZ Betrieb bei Kranbetrieb beachten?",
        vault_search=False,
        _script=[
            _LIVE_DSML,
            _WEBSEARCH_DSML,
            "Kran: schriftliche Beauftragung, jährliche Prüfung. Kein DSML.",
        ],
    )
    ans = res.get("answer") or ""
    tools = [t.get("tool") for t in (res.get("tool_calls") or [])]
    check("kein DSML in der Antwort", "DSML" not in ans, ans[:180])
    check("VaultFind (wiki) gelaufen", calls["vault"] >= 1, f"n={calls['vault']}")
    check("WebSearch gelaufen", "WebSearch" in tools, f"-> {tools}")


def main():
    print("=== Ordner-Suche Gate ===")
    test_off_searches_wiki_only()
    test_default_still_searches()
    test_selected_only()
    test_selected_pdf_is_read()
    test_llm_vaultfind_wiki_only()
    test_blocked_vaultfind_does_not_leak_dsml()
    print(f"\n=== Ergebnis: {OK} ok, {FAIL} Fehler ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
