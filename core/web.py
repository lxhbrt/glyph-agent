# -*- coding: utf-8 -*-
"""
Kontrollierte Web-Recherche (Ausbaustufe).

Wichtige Sicherheitsregel: Es gehen NUR bereinigte Suchanfragen an den
Webdienst (Exa, TinyFish). NIEMALS private Vault-Inhalte oder ungefilterte
Dokumente in die Suchanfrage einbetten. Der Aufrufer (Tool-Loop) bestätigt
die Anfrage, bevor sie rausgeht.

Zwei unabhängige Quellen (redundant, kein Single-Point-of-Failure):
  - Exa      -> EXA_API_KEY      (Klassische Websuche)
  - TinyFish -> TINYFISH_API_KEY (Suche + URL-Extraktion/Fetch als Zweitquelle)

Keys werden aus der Umgebung gelesen (core/dotenv.py lädt glyph-agent/.env) —
nicht fest im Code.
"""
import json
import os
import socket
import time
import urllib.request
import urllib.parse

# --- Exa --------------------------------------------------------------------
EXA_ENDPOINT = os.environ.get("EXA_ENDPOINT", "https://api.exa.ai/search")


def _exa_api_key():
    key = os.environ.get("EXA_API_KEY", "")
    if not key:
        raise RuntimeError(
            "EXA_API_KEY nicht gesetzt. Bitte in glyph-agent/.env bereitstellen."
        )
    return key


def search_exa(query, count=5, start_published_date=None):
    """
    Führt eine Exa-Suche durch. query darf nur anonymisierte/öffentliche
    Suchbegriffe enthalten. Liefert Liste von {title, url, snippet}.
    """
    payload = {
        "query": query,
        "numResults": count,
        # Inhalte anfordern, damit Snippets/Highlights gefüllt werden (sonst liefert
        # Exa leere Snippet-Texte und selbst gute Modelle können nichts auswerten).
        "contents": {"text": True, "highlights": True},
        "highlight": {"num_sentences": 2},
    }
    if start_published_date:
        payload["startPublishedDate"] = start_published_date
    req = urllib.request.Request(
        EXA_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": _exa_api_key(),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    results = []
    for r in data.get("results", []):
        snip = r.get("snippet") or ""
        # Exa liefert Highlights in r['highlights'] als Liste; fallback auf text.
        if not snip and r.get("highlights"):
            snip = " ".join(r["highlights"][:2])
        if not snip and r.get("text"):
            snip = r["text"][:300]
        results.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": snip[:400],
        })
    return results


# --- TinyFish ---------------------------------------------------------------
# Zwei Endpoints: Suche + URL-Extraktion/Fetch. Key via TINYFISH_API_KEY.
TINYFISH_SEARCH = "https://api.search.tinyfish.ai"
TINYFISH_EXTRACT = "https://agent.tinyfish.ai/v1/automation/run-sse"
TINYFISH_FETCH = "https://api.fetch.tinyfish.ai"


def _tinyfish_api_key():
    key = os.environ.get("TINYFISH_API_KEY", "")
    if not key:
        raise RuntimeError(
            "TINYFISH_API_KEY nicht gesetzt. Bitte in glyph-agent/.env bereitstellen."
        )
    return key


def search_tinyfish(query, count=5, location="DE", language="de"):
    """
    Websuche über TinyFish (Zweitquelle). Liefert Liste von {title, url, snippet}.
    """
    q = urllib.parse.quote(query)
    url = f"{TINYFISH_SEARCH}?query={q}&location={location}&language={language}"
    req = urllib.request.Request(url, headers={"X-API-Key": _tinyfish_api_key()})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    # TinyFish-Suchen liefern je nach Antwortform entweder eine Liste oder
    # ein Objekt mit "results". Tolerant normalisieren.
    rows = data if isinstance(data, list) else data.get("results", [])
    out = []
    for r in rows[:count]:
        if isinstance(r, str):
            out.append({"title": "", "url": r, "snippet": ""})
            continue
        out.append({
            "title": r.get("title", ""),
            "url": r.get("url", r.get("link", "")),
            "snippet": r.get("snippet", r.get("description", "")) or "",
        })
    return out


def extract_tinyfish(url, goal, timeout=None):
    """
    Besucht eine konkrete URL und extrahiert strukturierte Daten (JSON) nach
    `goal`. Hauptnutzen von TinyFish: Navigation + Extraktion auf Zielseite.

    time-bounded: Ein hänger/zu-langsamer PDF- oder Seiten-Abruf darf die gesamte
    Agenten-Antwort nicht blockieren. `timeout` (Sekunden, Default 12) erzwingt
    einen harten Abbruch: nach Ablauf wird KEIN weiteres COMPLETE abgewartet,
    sondern sofort ein schnelles {"error": "timeout"} geliefert, damit der
    Tool-Loop weiterarbeiten kann statt im ReAct-Nachlauf 40+ s festzuhängen.
    """
    if not url or not goal:
        raise RuntimeError("extract_tinyfish braucht url und goal.")
    timeout = timeout if timeout is not None else 12
    payload = json.dumps({"url": url, "goal": goal}).encode("utf-8")
    req = urllib.request.Request(
        TINYFISH_EXTRACT,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": _tinyfish_api_key(),
        },
        method="POST",
    )
    try:
        # SSE wird hier konsequent als Ganzes eingelesen, aber NUR bis `timeout`.
        # PDFs/JS-Seiten, die nicht in der Zeit ein COMPLETE liefern, werden so
        # schnell abgebrochen statt den Request unnötig am Leben zu halten.
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except (socket.timeout, TimeoutError):
        return {"error": f"timeout nach {timeout}s", "url": url}
    except Exception as e:
        return {"error": f"fetch fehlgeschlagen: {e}", "url": url}
    found = None
    deadline = time.monotonic() + timeout
    for line in raw.splitlines():
        if time.monotonic() > deadline:
            return {"error": f"timeout nach {timeout}s (Parsing)", "url": url}
        line = line.strip()
        if not line.startswith("data: "):
            continue
        try:
            d = json.loads(line[6:])
        except Exception:
            continue
        if d.get("type") == "COMPLETE":
            found = d.get("result")
        elif d.get("type") == "ERROR" or d.get("status") == "FAILED":
            return {"error": line[6:]}
    return found if found is not None else {"error": "kein COMPLETE", "url": url}


def fetch_tinyfish(url, fmt="markdown"):
    """
    Holt den Inhalt einer URL (markdown|text|html). Liefert Text/JSON.
    """
    payload = json.dumps({"urls": [url], "format": fmt}).encode("utf-8")
    req = urllib.request.Request(
        TINYFISH_FETCH,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": _tinyfish_api_key(),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


# --- Dispatch (für Tool-Registry) ------------------------------------------
def web_search(query, count=5, source="exa"):
    """
    Kontrollierte Websuche. source: "exa" (Standard) | "tinyfish".
    query darf nur anonymisierte Suchbegriffe enthalten.
    """
    if source == "tinyfish":
        return search_tinyfish(query, count=count)
    return search_exa(query, count=count)
