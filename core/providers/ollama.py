# -*- coding: utf-8 -*-
"""
Ollama — nur Embeddings-Infrastruktur-Hinweis.

Chat über Ollama ist in glyph-agent **entfernt**.
Embeddings (bge-m3) laufen direkt über core/retrieval.py + OLLAMA_URL.

Diese Datei bleibt als Stub, damit alte Imports nicht crashen —
jeder Chat-Aufruf wirft bewusst.
"""
from . import ModelProvider


class OllamaProvider(ModelProvider):
    """Entfernter Chat-Provider. Nicht mehr für Antworten nutzen."""

    def __init__(self, url=None, model=None):
        self.url = url
        self.model = model or "removed"

    @property
    def provider_name(self):
        return "ollama-removed"

    @property
    def model_name(self):
        return self.model

    def generate(self, prompt, temperature=0.3, num_ctx=8192):
        raise RuntimeError(
            "Lokaler Chat-Provider entfernt. Chat: Direct deepseek-v4-pro "
            "→ OpenRouter deepseek/deepseek-v4-flash-0731."
        )

    def chat(self, system, user, temperature=0.3, num_ctx=8192):
        raise RuntimeError(
            "Lokaler Chat-Provider entfernt. Chat: Direct deepseek-v4-pro "
            "→ OpenRouter deepseek/deepseek-v4-flash-0731."
        )
