# -*- coding: utf-8 -*-
"""
Kontrollierte Web-Recherche (Ausbaustufe).

Wichtige Sicherheitsregel: Es gehen NUR bereinigte Suchanfragen an den
Webdienst (Exa). NIEMALS private Vault-Inhalte oder ungefilterte Dokumente
in die Suchanfrage einbetten. Der Aufrufer (cli web) bestätigt die Anfrage,
bevor sie rausgeht.

Key wird aus der Umgebung gelesen (EXA_API_KEY) — nicht fest im Code.
"""
import json
import os
import urllib.request

EXA_ENDPOINT = os.environ.get("EXA_ENDPOINT", "https://api.exa.ai/search")


def search_web(query, count=5, start_published_date=None):
    """
    Führt eine Exa-Suche durch. query darf nur anonymisierte/öffentliche
    Suchbegriffe enthalten. Liefert Liste von {title, url, snippet}.
    """
    api_key = os.environ.get("EXA_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "EXA_API_KEY nicht gesetzt. Bitte in der Umgebung bereitstellen "
            "(z. B. in ~/.zshrc oder im .env)."
        )
    payload = {"query": query, "numResults": count, "contents": {"text": False}}
    if start_published_date:
        payload["startPublishedDate"] = start_published_date
    req = urllib.request.Request(
        EXA_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    results = []
    for r in data.get("results", []):
        results.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("snippet", "") or (r.get("text") or "")[:300],
        })
    return results
