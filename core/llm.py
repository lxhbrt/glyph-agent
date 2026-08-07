# -*- coding: utf-8 -*-
"""
Modelldienst — schmale Brücke auf die ModelProvider-Schnittstelle.

WICHTIG (Architektur): agent.py und die CLI rufen NUR diese Funktionen auf,
nie direkt einen Provider. Dadurch bleibt das Modell austauschbar, ohne dass
an der Agenten-/Tool-Schicht etwas geändert wird:

    core/llm.chat() / core/llm.generate()
        -> providers.get_provider()  (OpenRouter Luna → free)
            -> konkretes Modell

Die tatsächliche Provider-Implementierung liegt in core/providers/*.
Diese Datei darf KEINE provider-spezifische Logik enthalten.
"""
from .providers import factory


def get_provider():
    """Liefert den aktiven ModelProvider (für Logs/UI-Info)."""
    return factory.get_provider()


def chat(system, user, temperature=0.3, num_ctx=8192):
    """Chat-Aufruf an den aktiven Provider. Liefert Antworttext (str)."""
    return factory.get_provider().chat(system, user, temperature, num_ctx)


def generate(prompt, temperature=0.3, num_ctx=8192):
    """Freier Generierungs-Aufruf an den aktiven Provider. Liefert str."""
    return factory.get_provider().generate(prompt, temperature, num_ctx)
