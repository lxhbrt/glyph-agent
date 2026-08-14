# -*- coding: utf-8 -*-
"""
MLXProvider — lokales Modell über Apple MLX (spätere Option, Gerüst).

Aktuell nicht im B+-Chat-Pfad. Chat-Denker = OpenRouter (Luna → free).
"""
from . import ModelProvider


class MLXProvider(ModelProvider):
    def __init__(self, model=None):
        self.model = model or "unset"

    @property
    def provider_name(self):
        return "mlx"

    @property
    def model_name(self):
        return self.model

    def generate(self, prompt, temperature=0.3, num_ctx=8192):
        raise NotImplementedError(
            "MLXProvider ist ein Gerüst. Chat läuft über OpenRouter."
        )

    def chat(self, system, user, temperature=0.3, num_ctx=8192):
        raise NotImplementedError(
            "MLXProvider ist ein Gerüst. Chat läuft über OpenRouter."
        )
