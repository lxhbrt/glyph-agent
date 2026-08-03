# -*- coding: utf-8 -*-
"""
Routing — deterministische Entscheidung "Doku, Internet oder beides" für den
Tool-Loop (KEIN LLM-Call). Reine, testbare Funktionen.

Zielbild:
    Nutzerfrage
      ↓
    Aktualitäts-Signal?  ->  "current": WebSearch + VaultRecall parallel
      ↓ nein
    VaultRecall zuerst
      ↓
    ausreichend? (>=1 Treffer, status success)
      ├─ ja -> Antwort nur aus Doku
      └─ nein -> WebSearch nachziehen (beide Quellen)

Prinzipien:
  - Deterministisch (keine Score-Nähe-Logik, kein Unsicherheits-Flag).
  - "ausreichend" = selected >= 1 UND status == "success" (Minimal-Default).
  - Aktualitäts-Signale = Stichwort-Whitelist in der Frage („heute“, „aktuell“,
    „geltend“, „2026“, „Normen“, „Vorschriften“, …). Zerbrechlich, aber klein
    und ohne LLM; wird nur genutzt, um Web früh zu erlauben, nie um es zu verbieten.
"""
import os

# Klare Aktualitäts-/Web-Signale in der Frage -> WebSearch darf direkt dazukommen.
# Umfasst explizit Preis-/Markt-/Extern-Themen: Der Vault enthält selten aktuelle
# Preise/Normen/Regelungen; solche Fragen brauchen externe Recherche auch bei Vault-Treffer.
CURRENCY_SIGNALS = (
    "heute", "aktuell", "aktuelle", "aktuellen", "geltend", "geltende",
    "2026", "2025", "2027", "neu", "neue", "neueste", "Normen", "Norm",
    "Vorschriften", "Vorschrift", "Richtlinie", "Richtlinien", "vorgaben",
    "pflichten", "frist", "fristen", "letzter stand", "verordnung",
    # Externe/Markt-/aktualitätsbezogen: Preis, Kosten, Kauf, Vergütung, Markt
    "preis", "preise", "kosten", "kostet", "kaufen", "welpe", "welpenpreis",
    "vergleich", "markt", "angebot", "rabatt", "vergütung", "honorar",
    "gehalt", "lohn", "miete", "tarif", "gebühr", "gebühren", "rechnung",
)


def classify_intent(query):
    """
    Liefert "current" bei klaren Aktualitäts-Signalen, sonst "domain".

    "current"  -> WebSearch darf direkt (parallel zu VaultRecall) laufen.
    "domain"   -> VaultRecall zuerst; Web nur bei unzureichendem Ergebnis.
    """
    q = (query or "").lower()
    for sig in CURRENCY_SIGNALS:
        if sig.lower() in q:
            return "current"
    return "domain"


def is_sufficient(vault_result, min_selected=1):
    """
    Deterministische Antwort auf "reichen die Vault-Treffer?".

    vault_result: Rückgabe von retrieval.search() (dict mit status/selected/...)
      oder None.
    Ausreichend genau dann, wenn:
        status == "success"  UND  selected >= min_selected

    Kein Unsicherheits-Flag, keine Score-Nähe-Logik (Minimal-Default).
    """
    if not vault_result:
        return False
    if vault_result.get("status") != "success":
        return False
    return int(vault_result.get("selected") or 0) >= min_selected
