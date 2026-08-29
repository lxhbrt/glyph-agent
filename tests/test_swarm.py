#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Composer-Swarm: Planer → Suche → Synthese, ohne Netz."""
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


def test_parse_queries():
    from core.swarm import _parse_queries

    qs = _parse_queries('{"queries": ["alpha", "beta", "alpha"]}', "fallback")
    check("dedup + cap", qs == ["alpha", "beta"])
    check("fallback topic", _parse_queries("kein json", "Thema X") == ["Thema X"])
    check("empty raw", _parse_queries("", "T") == ["T"])


def test_run_swarm_injected():
    from core import swarm

    calls = {"plan": 0, "syn": 0}

    def chat(system, user, *a, **k):
        if "JSON" in system:
            calls["plan"] += 1
            return '{"queries": ["q1", "q2"]}'
        calls["syn"] += 1
        check("sources in synth", "https://example.com/a" in user)
        return "Kern: Beleg. https://example.com/a"

    def search(query, count=4):
        return [
            {
                "title": f"Hit {query}",
                "url": "https://example.com/a",
                "snippet": "snippet",
            }
        ]

    events = []
    res = swarm.run_swarm(
        "Postgres 17",
        chat_fn=chat,
        search_fn=search,
        on_event=events.append,
    )
    check("ok", res.get("ok") is True)
    check("swarm flag", res.get("swarm") is True)
    check("two queries", res.get("queries") == ["q1", "q2"])
    check("answer", "https://example.com/a" in (res.get("answer") or ""))
    check("plan+syn chat", calls["plan"] == 1 and calls["syn"] == 1)
    kinds = [e.get("action") for e in events if e.get("type") == "step"]
    check("steps", kinds[:1] == ["SwarmPlan"] and "SwarmSearch" in kinds)


def test_empty_topic():
    from core import swarm

    res = swarm.run_swarm("  ")
    check("empty rejected", res.get("ok") is False)


if __name__ == "__main__":
    print("test_swarm")
    test_parse_queries()
    test_run_swarm_injected()
    test_empty_topic()
    print(f"{OK} ok, {FAIL} fail")
    sys.exit(1 if FAIL else 0)
