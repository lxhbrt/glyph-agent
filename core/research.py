# -*- coding: utf-8 -*-
"""
Recherche-Policy (OpenClaw RECHERCHE.md → glyph-agent).

  Grob  = Exa (WebSearch, source=exa)  — Übersicht, Snippets, schnell
  Fein  = TinyFish (ExtractUrl / FetchUrl) — konkrete URL, strukturierte Daten

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
    fine  → TinyFish extract/fetch (oder WebSearch source=tinyfish als Zweitquelle)
    coarse → Exa WebSearch
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
    """source= für web_search: 'exa' (grob) oder 'tinyfish' (fein ohne URL)."""
    return "tinyfish" if classify_web_depth(query) == "fine" and not extract_urls(query) else "exa"


def policy_prompt_snippet() -> str:
    """Kurzer Text für System-Prompt."""
    return (
        "RECHERCHE: Exa = grobe Websuche (Übersicht). "
        "TinyFish ExtractUrl/FetchUrl = feine Zielseite (konkrete URL oder gezielte Extraktion). "
        "Keine privaten Vault-Texte in Suchanfragen."
    )
