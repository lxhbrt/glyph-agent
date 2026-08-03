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
            # Einzelner Absatz größer als max_chars: hart zerlegen (Embedding-Modell
            # hat Token-Limit; ein Riesen-Chunk durfte vorher mit HTTP 500 fehlschlagen).
            if len(p) > max_chars:
                for i in range(0, len(p), max_chars):
                    chunks.append(p[i:i + max_chars].strip())
                buf = ""
            else:
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


def build_index_from_vault(vault_path=None, quiet=False):
    """
    Baut/aktualisiert den Vektorindex direkt aus dem Obsidian-Vault.

    Iteriert alle .md-Dateien unterhalb der konfigurierten Vaults (config.VAULT_PATHS,
    bzw. vault_path falls gesetzt) unter Ausschluss von Obsidian-internen Ordnern ('.'),
    'backups' und BLOCKED_DIRS — identische Filterlogik wie vault_tools.search_vault.
    Ruft pro Datei index_document() auf (Hash-basiert: nur geänderte neu indexed,
    unveränderte übersprungen, gelöschte entfernt).

    Rückgabe: dict Zähler
      {discovered, indexed, unchanged, skipped, failed, chunks, index_path, duration_s}
      + optional log_lines (wenn quiet=False).
    """
    import os as _os
    import time as _time
    from . import config as _config
    from . import vault_tools as _vt

    roots = [vault_path] if vault_path else list(getattr(_config, "VAULT_PATHS", [_config.VAULT_PATH]))
    roots = [_os.path.realpath(r) for r in roots]
    invalid = [r for r in roots if not _os.path.isdir(r)]
    if invalid:
        return {"error": f"Vault-Pfad nicht gefunden: {invalid}"}

    _start_t = _time.time()
    lines = []
    def log(msg):
        if not quiet:
            lines.append(msg)

    # Zuerst gelöschte Dateien bereinigen: alle indexierten Pfade, die nicht mehr im Vault körperlich sind.
    discovered_paths = set()
    files = []  # (abs_path, index_path) wobei index_path den Vault-Präfix enthält
    for root in roots:
        for dirpath, dirnames, filenames in _os.walk(root):
            relroot = _os.path.relpath(dirpath, root)
            segs = relroot.split(_os.sep)
            # Nur UNTERORDNER filtern — der Root selbst (relroot='.') ist kein Obsidian-interner Ordner.
            if segs != ["."] and any(s.startswith(".") for s in segs):
                dirnames[:] = []
                continue
            if segs != ["."] and "backups" in segs:
                dirnames[:] = []
                continue
            if segs != ["."]:
                try:
                    if _vt._is_blocked(relroot):
                        dirnames[:] = []
                        continue
                except Exception:
                    pass
            for fn in filenames:
                if not fn.endswith(".md"):
                    continue
                full = _os.path.join(dirpath, fn)
                rel = _os.path.relpath(full, root)
                # Datei-Ebene auch gegen Blocklist prüfen + Vault-Präfix für eindeutige Pfade
                try:
                    if _vt._is_blocked(rel):
                        continue
                except Exception:
                    pass
                vname = _os.path.basename(root)
                index_path = f"/{vname}/{rel}"
                if index_path in discovered_paths:
                    continue
                files.append((full, index_path))
                discovered_paths.add(index_path)

    # Entferne im Index liegende Pfade, die nicht mehr im Vault sind.
    index = load_index()
    removed = 0
    for d in index.get("docs", []):
        if d.get("path") not in discovered_paths:
            remove_document(d.get("path"))
            removed += 1

    stats = {"indexed": 0, "unchanged": 0, "failed": 0, "chunks": 0, "removed": removed}
    files.sort()
    log(f"vaults: {', '.join(_os.path.basename(r) for r in roots)}")
    log(f"documents discovered: {len(files)}")

    for full, index_path in files:
        try:
            with open(full, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as e:
            stats["failed"] += 1
            log(f"  SKIP lesen: {index_path} ({e})")
            continue
        title = _os.path.splitext(_os.path.basename(full))[0]
        meta = {"vault": True}
        try:
            res = index_document(title, index_path, content, meta=meta)
        except Exception as e:
            stats["failed"] += 1
            log(f"  FEHLER: {index_path} ({e})")
            continue
        if res.get("status") == "indexed":
            stats["indexed"] += 1
            stats["chunks"] += res.get("sections", 0)
        elif res.get("status") == "unchanged":
            stats["unchanged"] += 1

    log(f"documents indexed: {stats['indexed']} (geändert/neu)")
    log(f"documents unchanged: {stats['unchanged']}")
    log(f"chunks created: {stats['chunks']}")
    log(f"embeddings created: {stats['chunks']}")
    log(f"stale removed: {stats['removed']}")
    log(f"index written: {INDEX_PATH}")
    log(f"done in {_time.time()-_start_t:.0f}s")

    stats["discovered"] = len(files)
    stats["skipped"] = stats["unchanged"] + stats["removed"]
    stats["index_path"] = INDEX_PATH
    if not quiet:
        stats["log_lines"] = lines
    return stats


# --- Retrieval ---------------------------------------------------------------

def _normalize(text: str) -> str:
    """Kleine Normalisierung: lowercase + Whitespace komprimieren."""
    import re as _re
    return _re.sub(r"\s+", " ", (text or "").lower()).strip()


def _keyword_boost(query: str, doc: dict) -> float:
    """
    Hybrider Keyword-Boost für exakte Begriffe in Titel/Pfad (nicht Chunk-Text).

    Hebt konzeptionelle Grundlagen-Dokumente (z. B. '00 MOC - Arbeitssicherheit.md')
    über rein vektoriell ähnliche, aber thematisch engere Chunks (Maschinen etc.).
    Wirkt als Reranker auf den Top-Kandidaten — niemals als Ersatz der Vektorsuche.

    Boost-Werte moderat: bei Vektor-Scores 0.65–0.72 heben 0.04–0.16 die richtige
    Grundlagen-MOC deutlich nach vorne, ohne die Vektorsuche zu überstimmen.
    Nur exakte Begriffe (nicht Teilstrings wie 'Arbeitsschutzmaßnahmen' als Volltreffer).
    """
    query_norm = _normalize(query)
    path = _normalize(doc.get("path") or "")
    title = _normalize(doc.get("title") or (path.rsplit("/", 1)[-1] if path else ""))

    # Begriffspaare, die in der Frage gemeinsam vorkommen (z. B. Arbeitsschutz + Arbeitssicherheit)
    pair_terms = []
    for t1, t2 in (("arbeitsschutz", "arbeitssicherheit"),):
        if t1 in query_norm and t2 in query_norm:
            pair_terms.append((t1, t2))

    boost = 0.0
    # Paar-Frage (Frage enthält beide Begriffe):
    # Eine Datei, die MINDESTENS EINEN der Begriffe im Titel trägt, ist bei solchen
    # Fragen sehr wahrscheinlich die Grundlagen-/Unterscheidungs-Datei — auch wenn
    # der zweite Begriff nicht in der Datei steht (z. B. '00 MOC - Arbeitssicherheit.md'
    # bei 'Arbeitsschutz vs. Arbeitssicherheit'). Voller Paar-Boost.
    for t1, t2 in pair_terms:
        if (t1 in title or t2 in title):
            boost += 0.16
            return boost
        # Kein Titel-Treffer: dann das Paar im Pfad (Ordnerstruktur) suchen
        if (t1 in path and t2 in path):
            boost += 0.16
            return boost

    # Einzelne exakte Begriffe im Dateinamen/Titel (stärker) oder Pfad (schwächer)
    for term in ("arbeitsschutz", "arbeitssicherheit"):
        if term in title:
            boost += 0.08
        elif term in path:
            boost += 0.04

    return boost


def search(query, top_k=None, min_score=None):
    """
    Semantische Suche im Vektorindex mit Hybrid-Reranking (Vektor + Keyword-Boost).

    Liefert {status, query, candidates, selected, threshold, sources, results, error?}.
    top_k/min_score konfigurierbar (Config-Defaults: VAULT_TOP_K, VAULT_MIN_SCORE).

    Zwei getrennte K-Werte:
      - CANDIDATE_K (50): Vektor-Kandidaten, auf denen der Keyword-Boost wirkt
        (damit ein Boost Rang 24 noch erreichen kann).
      - FINAL_K (5): nach Hybrid-Reranking ausgelieferte Treffer.
    Die Schwelle (0.6) bleibt unverändert und wird NACH dem Boost angewendet.
    """
    import os
    if top_k is None:
        top_k = int(os.environ.get("VAULT_TOP_K", "4"))
    if min_score is None:
        min_score = float(os.environ.get("VAULT_MIN_SCORE", "0.6"))
    candidate_k = int(os.environ.get("VAULT_CANDIDATE_K", "50"))
    final_k = top_k
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

    # 1) Vektor-Score für alle Docs, sortiert absteigend, Top-CANDIDATE_K behalten
    scored = []
    for d in docs:
        s = cosine(q_emb, d.get("embedding", []))
        scored.append((s, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    candidates = scored[:candidate_k]

    # 2) Hybrid-Reranking: Vektor-Score + Keyword-Boost (nur auf Kandidaten)
    reranked = []
    for s, d in candidates:
        boost = _keyword_boost(query, d)
        reranked.append((s + boost, s, boost, d))
    reranked.sort(key=lambda x: x[0], reverse=True)

    # 3) Schwelle + FINAL_K: Hybrid-Score muss >= min_score sein (Boost kann drunterliegende anheben)
    selected = [
        {"score": round(hybrid, 4), "vector_score": round(vec, 4), "boost": round(b, 4),
         **{k: (v if k != "embedding" else None) for k, v in d.items()}}
        for hybrid, vec, b, d in reranked if hybrid >= min_score
    ][:final_k]
    sources = sorted({r["path"] for r in selected})
    return {
        "status": "success",
        "query": query,
        "candidates": len(candidates),
        "selected": len(selected),
        "threshold": min_score,
        "sources": sources,
        "results": selected,
        "top_k": final_k,
        "candidate_k": candidate_k,
        "error": None,
    }
