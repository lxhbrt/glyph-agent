# -*- coding: utf-8 -*-
"""
Modelldienst — schmale Brücke auf die ModelProvider-Schnittstelle.

WICHTIG (Architektur): agent.py und die CLI rufen NUR diese Funktionen auf,
nie direkt einen Provider. Dadurch bleibt das Modell austauschbar, ohne dass
an der Agenten-/Tool-Schicht etwas geändert wird:

    core/llm.chat() / core/llm.generate()
        -> providers.get_provider()  (Direct Pro/Flash → OpenRouter Flash-0731)
            -> konkretes Modell

Die tatsächliche Provider-Implementierung liegt in core/providers/*.
Diese Datei darf KEINE provider-spezifische Logik enthalten.
"""
from .providers import factory


def get_provider():
    """Liefert den aktiven ModelProvider (für Logs/UI-Info)."""
    return factory.get_provider()


def short_model_label(model_id):
    """Nutzerlabel für Think-Steps: Pro / Direct-Flash / OpenRouter-Flash."""
    mid = str(model_id or "").strip()
    if not mid:
        return "?"
    low = mid.lower()
    if "deepseek-v4-pro" in low:
        return "DeepSeek v4 pro"
    if "deepseek-v4-flash-0731" in low:
        return "OpenRouter v4 flash" if "/" in mid else "DeepSeek v4 flash"
    if "deepseek-v4-flash" in low:
        return "OpenRouter v4 flash" if "/" in mid else "DeepSeek v4 flash"
    name = mid.split("/")[-1]
    return name.split(":")[0] or mid


def thinker_step_detail(kind="agent", model=None):
    """Think-Step-Detail aus Runtime — nie die alte Kette flash-0731 → free."""
    from . import config

    kind = (kind or "agent").lower()
    if kind == "code":
        configured = getattr(config, "CODE_OPENROUTER_MODEL", "deepseek-v4-flash")
        prefix = "DeepSeek CODE"
    else:
        configured = getattr(config, "AGENT_OPENROUTER_MODEL", "deepseek-v4-pro")
        prefix = "Cloud-Denker"
    used = model
    if not used:
        try:
            p = get_provider()
        except Exception:
            p = None
        last = getattr(p, "last_used", None) if p else None
        active = getattr(p, "_active_model", None) if p else None
        live = getattr(p, "model", None) if p else None
        used = active if (last and active) else (live or configured)
    return f"{prefix} denkt ({short_model_label(used)})"


def chat(system, user, temperature=0.3, num_ctx=8192):
    """Chat-Aufruf an den aktiven Provider. Liefert Antworttext (str)."""
    return factory.get_provider().chat(system, user, temperature, num_ctx)


def generate(prompt, temperature=0.3, num_ctx=8192):
    """Freier Generierungs-Aufruf an den aktiven Provider. Liefert str."""
    return factory.get_provider().generate(prompt, temperature, num_ctx)
