# -*- coding: utf-8 -*-
"""
MLXProvider — lokales Modell über Apple MLX (spätere Option).

GERÜST / Platzhalter: MLX (Apple MLX, mlx-lm) ist ein alternativer Weg,
das lokale Modell bereitzustellen (statt Ollama). Diese Datei ist bewusst
unvollständig — sie wird erst ausgebaut, wenn MLX tatsächlich genutzt wird.
Sie dokumentiert die Schnittstellen-Struktur, damit die Architektur stabil
bleibt.

Nutzen in core/config.py (Auswahl des Providers):
    PROVIDER = "ollama"   # oder "mlx"
"""
from . import ModelProvider


class MLXProvider(ModelProvider):
    def __init__(self, model=None):
        # TODO: MLX-Modellpfad/-name laden, z. B. "Qwen/Qwen3.5-9B-4bit"
        self.model = model or "unset"

    @property
    def provider_name(self):
        return "mlx"

    @property
    def model_name(self):
        return self.model

    def generate(self, prompt, temperature=0.3, num_ctx=8192):
        # TODO: mlx_lm.generate(...) anbinden, sobald MLX im Einsatz
        raise NotImplementedError(
            "MLXProvider ist ein Gerüst. Ausbauen, sobald MLX genutzt wird."
        )

    def chat(self, system, user, temperature=0.3, num_ctx=8192):
        # TODO: Chat-Verlauf + Systemprompt über mlx_lm
        raise NotImplementedError(
            "MLXProvider ist ein Gerüst. Ausbauen, sobald MLX genutzt wird."
        )
