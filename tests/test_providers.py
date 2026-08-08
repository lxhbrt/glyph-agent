#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Provider-Selbsttest — OpenRouter Luna → free, kein lokaler Chat.

Aufruf:
    python3 tests/test_providers.py
"""
import os
import sys
import importlib

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
    merged = {
        "AGENT_PRIMARY_PROVIDER": name,
        "MODE": "agent",
    }
    if env_overrides:
        merged.update(env_overrides)
    for k, v in merged.items():
        os.environ[k] = v
    factory.reset_provider()
    importlib.reload(config)
    config.PROVIDER = name if config.MODE != "openrouter-chat" else "openrouter"
    importlib.reload(factory)
    return factory.get_provider()


def test_trace_fallback_used():
    """fallback_used: True nur bei openrouter:free."""
    from core import tool_loop, llm

    class Fake:
        def __init__(self, pname, model, last_used=None, active=None):
            self.provider_name = pname
            self.model_name = model
            self.last_used = last_used
            if active is not None:
                self._active_model = active

    orig = llm.get_provider

    def with_provider(fake, fn):
        llm.get_provider = lambda: fake
        try:
            return fn()
        finally:
            llm.get_provider = orig

    with_provider(Fake("openrouter", "luna → free", "openrouter:free", "free-model"), lambda: (
        check(
            "free-Fallback -> fallback_used true",
            tool_loop._build_trace([], [], None).get("fallback_used") is True,
        )
    ))

    with_provider(Fake("fallback", "luna → free", "openrouter:free"), lambda: (
        check(
            "fallback+free -> fallback_used true",
            tool_loop._build_trace([], [], None).get("fallback_used") is True,
        )
    ))

    with_provider(Fake("openrouter", "luna", "openrouter", "openai/gpt-5.6-luna"), lambda: (
        check(
            "primär Luna -> fallback_used false",
            tool_loop._build_trace([], [], None).get("fallback_used") is False,
        )
    ))

    with_provider(Fake("openrouter", "gpt"), lambda: (
        check(
            "explizit True hat Vorrang",
            tool_loop._build_trace([], [], True).get("fallback_used") is True,
        )
    ))

    print("[trace-fallback] abgeschlossen.")


def main():
    print("=== Provider-Selbsttest ===\n")

    test_trace_fallback_used()

    print("\n[1] openrouter — ohne Key MUSS sauber fehlschlagen:")
    os.environ.pop("OPENROUTER_API_KEY", None)
    os.environ["MODE"] = "openrouter-chat"
    p = load("openrouter")
    check("provider_name == 'openrouter'", p.provider_name == "openrouter", f"-> {p.provider_name}")
    check(
        "Primär-Modell DeepSeek Flash",
        "deepseek-v4-flash" in (p.model or ""),
        f"-> {getattr(p, 'model', p.model_name)}",
    )
    try:
        p.chat("s", "u")
        check("Ohne Key blockiert", False, "<- hat NICHT geblockt!")
    except RuntimeError as e:
        check("Ohne Key blockiert", True, f"-> RuntimeError: {str(e)[:40]}")

    print("\n[2] fallback — 2-stufige Cloud-Kette (kein lokal):")
    p = load("fallback", {
        "OPENROUTER_URL": "http://127.0.0.1:1",
        "OPENROUTER_API_KEY": "test",
        "MODE": "agent",
        "AGENT_PRIMARY_PROVIDER": "fallback",
        "AGENT_OPENROUTER_MODEL": "deepseek/deepseek-v4-flash-0731",
        "AGENT_OPENROUTER_FALLBACK_MODEL": "inclusionai/ling-3.0-flash:free",
    })
    check("provider_name == 'fallback'", p.provider_name == "fallback", f"-> {p.provider_name}")
    check("Modell zeigt Kette (→)", "→" in p.model_name, f"-> {p.model_name}")
    check("kein 'lokal' im Modellnamen", "lokal" not in p.model_name.lower(), f"-> {p.model_name}")
    try:
        p.chat("Du.", "Sag nur: OK")
        check("Beide Cloud-Stufen down -> harter Fehler", False, "<- hat nicht geworfen")
    except Exception as e:
        check(
            "Beide Cloud-Stufen down -> harter Fehler",
            True,
            f"-> {type(e).__name__}: {str(e)[:50]}",
        )
        check("last_used nie 'local'", getattr(p, "last_used", None) != "local")

    print("\n[3] veralteter Name 'ollama' wird auf openrouter umgebogen:")
    os.environ["OPENROUTER_API_KEY"] = "test"
    p = load("ollama", {"MODE": "agent", "AGENT_PRIMARY_PROVIDER": "ollama"})
    # factory maps ollama → openrouter
    check(
        "ollama-Alias lädt openrouter",
        p.provider_name == "openrouter",
        f"-> {p.provider_name}",
    )

    print("\n[4] Kürzungsschranke (EXTERNAL_MAX_CHARS) im Tool-Loop:")
    from core import tool_loop
    cap = getattr(config, "EXTERNAL_MAX_CHARS", 4000)
    big = [{"tool": "ReadNote", "args": {"path": "x.md"}, "result": {"content": "A" * (cap + 5000)}}]
    os.environ["AGENT_PRIMARY_PROVIDER"] = "openrouter"
    importlib.reload(config)
    importlib.reload(tool_loop)
    out = tool_loop._fmt_tool_results(big)
    check(f"Kürzung auf ~{cap} bei openrouter", len(out) <= cap + 150, f"-> {len(out)} Zeichen")

    print(f"\n=== Ergebnis: {OK} ok, {FAIL} Fehler ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
