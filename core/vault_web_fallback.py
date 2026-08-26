# -*- coding: utf-8 -*-
"""Leere Ordner-Suche: KomNet einmal, sonst DGUV — über Exa+TinyFish, nicht HTML."""
import threading
import time
import urllib.parse

_SKIP_DGUV_HOSTS = ("diva-online.dguv.de",)
_KOMNET_DOMAINS = ("komnet.nrw.de",)
_DGUV_DOMAINS = ("dguv.de",)


def run_deadline(fn, deadline, default):
    """Call fn, but return default if deadline (monotonic) has passed or is hit."""
    remaining = None if deadline is None else (deadline - time.monotonic())
    if remaining is not None and remaining <= 0:
        return default
    if remaining is None:
        try:
            return fn()
        except Exception:
            return default
    box = [default]

    def _run():
        try:
            box[0] = fn()
        except Exception:
            pass

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(remaining)
    return box[0]


def fallback_web_hits(query, vault_hit_count=0, search_komnet=None, search_dguv=None, deadline=None):
    """Nur wenn der Vault leer ist. KomNet zuerst; DGUV nur bei 0 KomNet-Treffern."""
    if int(vault_hit_count or 0) > 0:
        return {"hits": [], "tried": [], "source": None}
    q = (query or "").strip()
    if not q:
        return {"hits": [], "tried": [], "source": None}
    if deadline is not None and deadline - time.monotonic() <= 0:
        return {"hits": [], "tried": [], "source": None}
    komnet_fn = search_komnet or search_komnet_site
    dguv_fn = search_dguv or search_dguv
    tried = ["komnet"]
    hits = run_deadline(lambda: list(komnet_fn(q) or []), deadline, [])
    if not isinstance(hits, list):
        hits = []
    if hits:
        return {"hits": hits, "tried": tried, "source": "komnet"}
    if deadline is not None and deadline - time.monotonic() <= 0:
        return {"hits": [], "tried": tried, "source": None}
    tried.append("dguv")
    hits = run_deadline(lambda: list(dguv_fn(q) or []), deadline, [])
    if not isinstance(hits, list):
        hits = []
    return {"hits": hits, "tried": tried, "source": "dguv" if hits else None}


def search_komnet_site(query, search=None, limit=8):
    return _site_hits(
        query,
        source="komnet",
        domains=_KOMNET_DOMAINS,
        allow=_is_komnet_url,
        search=search,
        limit=limit,
    )


def search_dguv(query, search=None, limit=8):
    return _site_hits(
        query,
        source="dguv",
        domains=_DGUV_DOMAINS,
        allow=_is_dguv_url,
        search=search,
        limit=limit,
    )


def _site_hits(query, source, domains, allow, search=None, limit=8):
    q = (query or "").strip()
    if not q:
        return []
    fn = search or _default_web_search
    try:
        rows = fn(q, count=limit, include_domains=list(domains))
    except TypeError:
        try:
            rows = fn(q, count=limit)
        except Exception:
            rows = []
    except Exception:
        rows = []
    hits = []
    seen = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if not allow(url) or url in seen:
            continue
        seen.add(url)
        hits.append(
            _web_hit(
                url,
                str(row.get("title") or ""),
                str(row.get("snippet") or row.get("text") or ""),
                source,
            )
        )
        if len(hits) >= limit:
            break
    return hits


def _web_hit(url, title, excerpt, source):
    title = (title or "").strip() or url.rsplit("/", 1)[-1] or url
    excerpt = (excerpt or "").strip()
    if len(excerpt) > 240:
        excerpt = excerpt[:240].rstrip() + "…"
    return {
        "id": f"web:{url}"[:200],
        "kind": "web",
        "path": url,
        "title": title[:200],
        "excerpt": excerpt,
        "source": source,
        "score": None,
    }


def _is_komnet_url(url):
    host = _host(url)
    return host == "komnet.nrw.de" or host.endswith(".komnet.nrw.de")


def _is_dguv_url(url):
    host = _host(url)
    if not host:
        return False
    if host in _SKIP_DGUV_HOSTS or host.endswith(".diva-online.dguv.de"):
        return False
    return host == "dguv.de" or host.endswith(".dguv.de")


def _host(url):
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _default_web_search(query, count=8, include_domains=None):
    from . import web

    return web.web_search(
        query,
        count=count,
        source="both",
        include_domains=include_domains,
    )
