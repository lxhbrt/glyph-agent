# -*- coding: utf-8 -*-
"""
Vault-Recall (Stufe B): semantische Suche über den Vault mit lokalen Embeddings.

- Embeddings: nomic-embed-text via Ollama (lokal, DSGVO-sauber, modellunabhängig).
- Vektorindex: persistent in einer JSON-Datei (Embedding + Metadaten), Hash-basiert.
- Retrieval: Kosinus-Ähnlichkeit, top_k + Mindestschwellwert (konfigurierbar).
- Quellen bleiben in den Treffern erhalten (Dokument, Titel, Pfad, Abschnitt).
- Strikte Trennung von WebSearch (eigenes Modul; agiert nie automatisch).

Sicherheit/Datenschutz: Nur lokale Embeddings; nichts verlässt den Rechner.
"""
import hashlib
import json
import os
import time
import urllib.request

from . import config

EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
# Vektorindex-Datei (unter logs/, leicht, persistiert zwischen Läufen).
INDEX_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "logs", "vault_index.json"
)


# --- Embedding ---------------------------------------------------------------

def embed_text(text):
    """Erzeugt ein Embedding für text via lokalem Ollama-Modell. Liefert Liste[float]."""
    if not text or not text.strip():
        return []
    payload = {"model": EMBED_MODEL, "prompt": text.strip()}
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embeddings",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("embedding", [])


# --- Abschnitts-Splitting ----------------------------------------------------

def split_document(content, title, path, max_chars=1200):
    """
    Zerlegt einen Dokument-Inhalt in sinnvolle Abschnitte (an Absatz-/Überschrift-
    Grenzen, ~max_chars). Liefert Liste von {id, title, path, section, text, ts}.
    """
    from . import config as _cfg
    text = (content or "").strip()
    if not text:
        return []
    # Grob an Leerzeilen/Überschriften aufteilen, dann zu Blöcken bündeln.
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    buf = ""
    for p in paragraphs:
        if len(buf) + len(p) + 2 <= max_chars:
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            if buf:
                chunks.append(buf)
            buf = p
    if buf:
        chunks.append(buf)

    ts = int(time.time())
    out = []
    for i, chunk in enumerate(chunks):
        sec = chunk.split("\n", 1)[0][:80] if chunk else f"{filename_stub(title)}-{i}"
        out.append({
            "id": f"{hashlib.sha1(f'{path}#{i}'.encode()).hexdigest()[:16]}",
            "title": title,
            "path": path,
            "section": sec,
            "text": chunk,
            "ts": ts,
        })
    return out


def filename_stub(s):
    return "".join(c for c in (s or "doc") if c.isalnum() or c in " _-")[:40] or "doc"


# --- Kosinus-Ähnlichkeit -----------------------------------------------------

def cosine(a, b):
    """Kosinus-Ähnlichkeit zweier Embeddings. Handschriftlich (keine numpy-Pflicht)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# --- Index-Persistenz (JSON) -------------------------------------------------

def load_index():
    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "docs": []}


def save_index(index):
    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
    tmp = INDEX_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    os.replace(tmp, INDEX_PATH)


def doc_hash(text):
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


# --- Index-Aufbau / Aktualisierung ------------------------------------------

def index_document(title, path, content, meta=None):
    """
    Indiziert/aktualisiert ein Dokument im Vektorindex. Ersetzt alte Embeddings des
    Pfads bei Änderung (Hash), ignoriert bei unverändertem Hash. Entfernt gelöschte.
    """
    index = load_index()
    h = doc_hash(content)
    existing = [d for d in index["docs"] if d["path"] == path]
    if existing and existing[0]["hash"] == h:
        return {"status": "unchanged", "path": path}

    sections = split_document(content, title, path)
    entries = []
    for sec in sections:
        emb = embed_text(sec["text"])
        if emb:
            entries.append({**sec, "embedding": emb})
    # Alte Einträge desselben Pfads entfernen, neue einfügen.
    index["docs"] = [d for d in index["docs"] if d["path"] != path]
    for e in entries:
        meta_clean = {k: v for k, v in (meta or {}).items()}
        e["hash"] = h
        e["meta"] = meta_clean
        index["docs"].append(e)
    index["docs"].sort(key=lambda d: d["path"])
    save_index(index)
    return {"status": "indexed", "path": path, "sections": len(entries)}


def remove_document(path):
    """Entfernt alle Einträge eines Pfads aus dem Index (gelöschtes Dokument)."""
    index = load_index()
    before = len(index["docs"])
    index["docs"] = [d for d in index["docs"] if d["path"] != path]
    save_index(index)
    return {"removed": before - len(index["docs"])}


# --- Retrieval ---------------------------------------------------------------

def search(query, top_k=None, min_score=None):
    """
    Semantische Suche im Vektorindex. Liefert {status, query, candidates,
    selected, threshold, sources, results, error?}. top_k/min_score konfigurierbar
    (Config-Defaults: VAULT_TOP_K, VAULT_MIN_SCORE).
    """
    import os
    if top_k is None:
        top_k = int(os.environ.get("VAULT_TOP_K", "4"))
    if min_score is None:
        min_score = float(os.environ.get("VAULT_MIN_SCORE", "0.6"))
    index = load_index()
    docs = index.get("docs", [])
    if not docs:
        return {
            "status": "empty", "query": query, "candidates": 0, "selected": 0,
            "threshold": min_score, "sources": [], "results": [],
        }
    q_emb = embed_text(query)
    if not q_emb:
        return {"status": "error", "query": query, "error": "Embedding fehlgeschlagen"}
    scored = []
    for d in docs:
        s = cosine(q_emb, d.get("embedding", []))
        scored.append((s, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [{"score": s, **{k: (v if k != "embedding" else None) for k, v in d.items()}}
                for s, d in scored if s >= min_score][:top_k]
    sources = sorted({r["path"] for r in selected})
    return {
        "status": "success",
        "query": query,
        "candidates": len(scored),
        "selected": len(selected),
        "threshold": min_score,
        "sources": sources,
        "results": selected,
        "top_k": top_k,
        "error": None,
    }
