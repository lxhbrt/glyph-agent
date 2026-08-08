# -*- coding: utf-8 -*-
"""
ModelProvider — stabile Modell-Schnittstelle (austauschbarer Modell-Adapter).

Der Agent (core/agent.py) spricht NUR mit dieser Schnittstelle, nie direkt
mit einem konkreten Provider. Chat-Denker laufen über OpenRouter (Luna → free).

    Agent
     └── ModelProvider            <-- diese Datei (Schnittstelle)
           ├── OpenRouterProvider <-- core/providers/openrouter.py
           └── FallbackProvider   <-- core/providers/fallback.py (Alias-Kette)

Schnittstellen-Methoden (fester Vertrag, bleibt stabil):
    - generate(prompt, temperature, num_ctx) -> str
    - chat(system, user, temperature, num_ctx) -> str
"""
from abc import ABC, abstractmethod


class ModelProvider(ABC):
    """Abstrakte Schnittstelle. Alle konkreten Provider implementieren sie."""

    @abstractmethod
    def generate(self, prompt, temperature=0.3, num_ctx=8192):
        """Freier Textgenerator (ohne Chat-Verlauf). Liefert str."""

    @abstractmethod
    def chat(self, system, user, temperature=0.3, num_ctx=8192):
        """Chat mit System-Prompt. Liefert str."""

    @property
    @abstractmethod
    def provider_name(self):
        """Z. B. 'openrouter' oder 'fallback'."""

    @property
    @abstractmethod
    def model_name(self):
        """Z. B. 'deepseek/deepseek-v4-flash-0731' oder Kette 'flash → free'."""
