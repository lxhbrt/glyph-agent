# -*- coding: utf-8 -*-
"""
Lokales LLM-Interface — spricht mit Ollama (lokales Qwen-Modell).

Hält alle Modellaufrufe an EINER Stelle (Architektur-Regel: nicht überall
direkt einbauen). Nur stdlib urllib — keine externen Abhängigkeiten.
"""
import json
import urllib.request

from . import config


def chat(system, user, temperature=0.3, num_ctx=8192):
    """
    Einfacher Chat-Aufruf an das lokale Ollama-Modell.
    Liefert den reinen Antworttext (str) zurück.
    """
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
        },
    }
    req = urllib.request.Request(
        f"{config.OLLAMA_URL}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("message", {}).get("content", "").strip()


def generate(prompt, temperature=0.3, num_ctx=8192):
    """
    Einfacher generate-Aufruf (ohne Chat-Verlauf) — für Einzel-Tasks.
    Liefert Antworttext zurück.
    """
    payload = {
        "model": config.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": num_ctx},
    }
    req = urllib.request.Request(
        f"{config.OLLAMA_URL}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("response", "").strip()
