# -*- coding: utf-8 -*-
"""
OllamaProvider — lokales Modell über Ollama (localhost:11434).

Implementiert die ModelProvider-Schnittstelle. Ollama ist NUR EIN
austauschbarer Weg, das lokale Modell bereitzustellen — ersetzbar durch
MLXProvider oder andere, ohne an der Architektur etwas zu ändern.
"""
import json
import urllib.request

from .. import config
from . import ModelProvider


class OllamaProvider(ModelProvider):
    def __init__(self, url=None, model=None):
        self.url = url or config.OLLAMA_URL
        self.model = model or config.OLLAMA_MODEL

    @property
    def provider_name(self):
        return "ollama"

    @property
    def model_name(self):
        return self.model

    def generate(self, prompt, temperature=0.3, num_ctx=8192):
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_ctx": num_ctx},
        }
        data = self._post("/api/generate", payload)
        return data.get("response", "").strip()

    def chat(self, system, user, temperature=0.3, num_ctx=8192):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": temperature, "num_ctx": num_ctx},
        }
        data = self._post("/api/chat", payload)
        return data.get("message", {}).get("content", "").strip()

    def _post(self, path, payload):
        req = urllib.request.Request(
            f"{self.url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode("utf-8"))
