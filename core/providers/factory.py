# -*- coding: utf-8 -*-
"""
Provider-Factory — wählt den aktiven Modell-Provider anhand der Konfiguration.

Der Rest des Codes (Agent, CLI) bezieht den Provider NUR über get_provider()
und kennt nie die konkrete Klasse. Damit bleibt der Modellaustausch zentral
(in core/config.py gesteuert).
"""
from .. import config
from .ollama import OllamaProvider
from .mlx import MLXProvider
from .openrouter import OpenRouterProvider
from .fallback import FallbackProvider

_PROVIDERS = {
    "ollama": lambda: OllamaProvider(),
    "mlx": lambda: MLXProvider(),
    "openrouter": lambda: OpenRouterProvider(),
    "fallback": lambda: FallbackProvider(),
}

_singleton = None


def get_provider():
    """
    Liefert den aktiven ModelProvider (Singleton). Auswahl über
    config.PROVIDER ('ollama' | 'mlx'). Fällt bei unbekanntem Wert auf ollama.
    """
    global _singleton
    if _singleton is None:
        name = getattr(config, "PROVIDER", "ollama") or "ollama"
        factory = _PROVIDERS.get(name)
        if factory is None:
            raise ValueError(f"Unbekannter Provider-Konfiguration: {name}")
        _singleton = factory()
    return _singleton


def reset_provider():
    """Setzt den Singleton zurück (Tests / Provider-Wechsel zur Laufzeit)."""
    global _singleton
    _singleton = None
