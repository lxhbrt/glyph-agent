# -*- coding: utf-8 -*-
"""
ModelProvider — stabile Modell-Schnittstelle (austauschbarer Modell-Adapters).

Der Agent (core/agent.py) spricht NUR mit dieser Schnittstelle, nie direkt
mit einem konkreten Provider (Ollama/MLX/sonst). Damit bleibt Qwen, Ollama
oder das gesamte lokale Modell austauschbar, ohne die Architektur zu ändern:

    Agent
     └── ModelProvider            <-- diese Datei (Schnittstelle)
           ├── OllamaProvider     <-- core/providers/ollama.py
           └── MLXProvider        <-- core/providers/mlx.py (später)

Schnittstellen-Methoden (fester Vertrag, bleibt stabil):
    - generate(prompt, temperature, num_ctx) -> str
    - chat(system, user, temperature, num_ctx) -> str
"""
from abc import ABC, abstractmethod


class ModelProvider(ABC):
    """Abstrakte Schnittstelle. Alle konkreten Provider implementieren sie."""

    # --- Einzel-Aufrufe (der Agent nutzt diese; nie Provider-Details) ---
    @abstractmethod
    def generate(self, prompt, temperature=0.3, num_ctx=8192):
        """Freier Textgenerator (ohne Chat-Verlauf). Liefert str."""

    @abstractmethod
    def chat(self, system, user, temperature=0.3, num_ctx=8192):
        """Chat mit System-Prompt. Liefert str."""

    # --- Info (für Logs/UI) ---
    @property
    @abstractmethod
    def provider_name(self):
        """Z. B. 'ollama' oder 'mlx'."""

    @property
    @abstractmethod
    def model_name(self):
        """Z. B. 'qwen-solid' oder 'Qwen3.5-9B'."""
