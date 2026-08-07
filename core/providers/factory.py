# -*- coding: utf-8 -*-
"""
Provider-Factory — wählt den aktiven Modell-Provider anhand der Konfiguration.

Der Rest des Codes (Agent, CLI) bezieht den Provider NUR über get_provider()
und kennt nie die konkrete Klasse. Damit bleibt der Modellaustausch zentral
(in core/config.py gesteuert).

Chat-Provider: openrouter | fallback (beide Cloud, Luna → free).
Kein lokaler Chat-Provider.
"""
from .. import config
from .mlx import MLXProvider
from .openrouter import OpenRouterProvider
from .fallback import FallbackProvider

_PROVIDERS = {
    "mlx": lambda: MLXProvider(),
    "openrouter": lambda: OpenRouterProvider(),
    "fallback": lambda: FallbackProvider(),
}

_singleton = None


def get_provider():
    """
    Liefert den aktiven ModelProvider (Singleton).
    Auswahl über config.PROVIDER ('openrouter' | 'fallback' | 'mlx').
    Unbekannt → openrouter (B+-Default).
    """
    global _singleton
    if _singleton is None:
        name = getattr(config, "PROVIDER", "openrouter") or "openrouter"
        # Veralteter Name "ollama" als Chat-Provider: hart auf openrouter umbiegen.
        if name == "ollama":
            name = "openrouter"
        factory = _PROVIDERS.get(name)
        if factory is None:
            raise ValueError(f"Unbekannte Provider-Konfiguration: {name}")
        _singleton = factory()
    return _singleton


def reset_provider():
    """Setzt den Singleton zurück (Tests / Provider-Wechsel zur Laufzeit)."""
    global _singleton
    _singleton = None
