# -*- coding: utf-8 -*-
"""
Recherche-Policy (OpenClaw RECHERCHE.md → glyph-agent).

  Suche = Exa + TinyFish parallel (WebSearch, source=both)
  Fein  = TinyFish ExtractUrl / FetchUrl — konkrete URL

Keine privaten Vault-Inhalte in Suchqueries. Reine Policy-Helfer, kein Netzwerk.
"""
import re

# Signale für „Fein“: Nutzer hat schon eine URL oder will explizit extrahieren.
FINE_SIGNALS = (
    "http://", "https://", "www.",
    "extrahier", "zieh mir", "von der seite", "von dieser url",
    "zielseite", "tabelleninhalt", "fetch", "scrape",
)

# Signale für grobe Websuche (zusätzlich zu routing.CURRENCY_SIGNALS).
COARSE_OK = True  # Default: grobe Suche wenn need_web


def classify_web_depth(query: str) -> str:
    """
    Liefert 'fine' | 'coarse'.
    fine  → TinyFish extract/fetch bei konkreter URL
    coarse → WebSearch (Exa + TinyFish)
    """
    q = (query or "").lower()
    for sig in FINE_SIGNALS:
        if sig in q:
            return "fine"
    # URL-Muster
    if re.search(r"https?://\S+", query or ""):
        return "fine"
    return "coarse"


def extract_urls(query: str):
    """Alle http(s)-URLs aus der Frage."""
    return re.findall(r"https?://[^\s<>\"']+", query or "")


def default_web_source(query: str) -> str:
    """source= für web_search: immer beide (Exa + TinyFish)."""
    return "both"


def policy_prompt_snippet(web=None) -> str:
    """Kurzer Text für System-Prompt.

    web: None = Jobs/Default; 'open' = ohne Apfel; 'apple' = Ordner-Suche an.
    TinyFish + Exa immer.
    """
    base = (
        "RECHERCHE: WebSearch = Exa und TinyFish parallel. "
        "TinyFish ExtractUrl/FetchUrl = feine Zielseite (konkrete URL). "
        "Keine privaten Vault-Texte in Suchanfragen."
    )
    if web == "open":
        return (
            base
            + " Ordner-Suche aus: allgemeine Suche, Internet, soziale Netze. "
            "Nicht den KomNet/DGUV-Pfad der Ordner-Suche."
        )
    if web == "apple":
        return (
            base
            + " Ordner-Suche an: KomNet und DGUV. "
            "Keine allgemeine Websuche, keine sozialen Netze."
        )
    return base
