# -*- coding: utf-8 -*-
"""
OpenRouterProvider — Cloud-Modell über OpenRouter (optional).

Implementiert die ModelProvider-Schnittstelle. WICHTIG (Datenschutz):
Dieser Provider sendet den übergebenen Text an OpenRouter (Cloud, kostenpflichtig).
Der Tool-Loop (core/tool_loop.py) entscheidet, was hier ankommt — es dürfen NUR
minimierte, anonymisierte Ausschnitte sein, nie der vollständige Vault oder
personenbezogene Daten. Kein direkter Vault-Zugriff von hier.

Key: OPENROUTER_API_KEY aus der Umgebung (glyph-agent/.env), nicht im Code.
"""
import json
import os
import time
import urllib.request

from . import ModelProvider
from .. import log as _agent_log
from .. import config as _cfg


class OpenRouterProvider(ModelProvider):
    def __init__(self, url=None, model=None, api_key=None):
        self.url = url or os.environ.get("OPENROUTER_URL", "https://openrouter.ai/api/v1")
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        # Modell-Default abhängig vom Modus (openrouter-chat vs. agent):
        default_model = os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-chat")
        if getattr(_cfg, "MODE", "agent") == "agent":
            default_model = os.environ.get("AGENT_OPENROUTER_MODEL", "deepseek/deepseek-chat")
        self.model = model or default_model

    @property
    def provider_name(self):
        return "openrouter"

    @property
    def model_name(self):
        return self.model

    def _ensure_key(self):
        if not self.api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY nicht gesetzt (glyph-agent/.env). "
                "Cloud-Modell nicht verfügbar."
            )

    def _chat_completion(self, messages, temperature, timeout=60):
        self._ensure_key()
        # Protokollieren, was an die Cloud geht (Datenschutz-Audit).
        total_chars = sum(len(m.get("content", "")) for m in messages)
        _agent_log.log(
            "cloud_send",
            provider=self.provider_name,
            model=self.model,
            chars=total_chars,
            n_messages=len(messages),
        )
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        req = urllib.request.Request(
            f"{self.url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()

    def generate(self, prompt, temperature=0.3, num_ctx=8192):
        return self._chat_completion(
            [{"role": "user", "content": prompt}], temperature
        )

    def chat(self, system, user, temperature=0.3, num_ctx=8192):
        return self._chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature,
        )
