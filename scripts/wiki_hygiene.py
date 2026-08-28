#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Glyph Wiki-Hygiene (memory-wiki).

Deterministisch, kein LLM — analog memory_hygiene.py.
  1) Tote Wiki-Links ([[Link]]); eindeutiger Stem → Text ersetzen
  2) Doppelt tote Dateien → _hygiene-trash/YYYY-MM-DD/ (30 Tage, dann weg)
     summaries/, sources/grok-sessions/, unsafe-local-*, unverlinkte Sources
  3) Secret- & PII-Scan auf Markdown
  4) agent-digest.json an den Dateibaum anpassen
  5) Report nach reports/hygiene.md — nicht pending-contract

Chat (°_Agent) löscht weiter nichts. Dieser Job nur memory-wiki, nie HSEQ/Privat.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")
GLYPH = os.path.expanduser("~/.glyph")
PENDING_CONTRACT = os.path.join(GLYPH, "memory", "pending-contract.md")
DIGEST_REL = os.path.join(".openclaw-wiki", "cache", "agent-digest.json")

_RE_WIKI_LINK = re.compile(r"\[\[([^\]\|#]+)(?:#[^\]\|]+)?(?:\|[^\]]+)?\]\]")
_RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_RE_PHONE = re.compile(r"(?<!\d)(?:\+49|0049|0)\s*[\d\s\-/\(\)]{8,18}\d")
_RE_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
_RE_SECRET = re.compile(
    r"\b(?:ghp_[a-zA-Z0-9]{36}|sk-[a-zA-Z0-9]{32,}|xai-[a-zA-Z0-9]{40,}|"
    r"AIza[0-9A-Za-z-_]{35}|Bearer\s+[a-zA-Z0-9_\-\.]{20,})\b"
)

_ALLOW = (
    "alexander hubert",
    "+4915118567252",
)

_KIND_BY_DIR = {
    "sources": "source",
    "concepts": "concept",
    "entities": "entity",
    "syntheses": "synthesis",
    "reports": "report",
    "summaries": "source",
}

_SKIP_FILES = {"agents.md", "wiki.md"}
TRASH_REL = "_hygiene-trash"
RETENTION_DAYS = 30
_KEEP_PREFIXES = ("concepts/", "entities/", "syntheses/", "reports/")
_KEEP_BASENAMES = {"agents.md", "wiki.md", "inbox.md", "index.md"}
_PENDING_HYGIENE_RE = re.compile(
    r"^- \d{4}-\d{2}-\d{2} · memory-wiki · Wiki-Hygiene:.*job td-wiki-hygiene\s*$"
)


def _find_wiki_dir() -> str | None:
    vaults_cfg = os.path.join(GLYPH, "vaults.json")
    if os.path.isfile(vaults_cfg):
        try:
            with open(vaults_cfg, encoding="utf-8") as f:
                data = json.load(f)
            for v in data.get("vaults") or []:
                name = str(v.get("name") or "").lower()
                path = str(v.get("path") or "")
                if "memory-wiki" in name or "memory-wiki" in path.lower():
                    p = os.path.expanduser(path)
                    if os.path.isdir(p):
                        return p
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    cand = os.path.expanduser("~/ObsidianVaults/memory-wiki")
    if os.path.isdir(cand):
        return cand
    return None


def _walk_wiki(wiki_root: str):
    """notes: rel→path (nicht sources/), sources: rel-set, stems: alle .md-Basenames."""
    notes: dict[str, str] = {}
    sources: set[str] = set()
    stems: set[str] = set()
    md_files: list[tuple[str, str]] = []  # (rel, full) all markdown

    for root, dirs, files in os.walk(wiki_root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and not d.startswith("_")]
        for name in files:
            if name.startswith("."):
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, wiki_root).replace("\\", "/")
            if rel.lower() in _SKIP_FILES or os.path.basename(rel).lower() in _SKIP_FILES:
                continue
            if rel.startswith("sources/"):
                sources.add(rel)
            if name.endswith(".md"):
                stems.add(os.path.splitext(os.path.basename(name))[0])
                md_files.append((rel, full))
                if not rel.startswith("sources/"):
                    notes[rel] = full
    return notes, sources, stems, md_files


def _link_live(target: str, stems: set[str], sources: set[str]) -> bool:
    raw = (target or "").strip().replace("\\", "/")
    if not raw:
        return True
    stem = os.path.splitext(os.path.basename(raw))[0]
    if stem in stems:
        return True
    if raw in sources or f"{raw}.md" in sources:
        return True
    for src in sources:
        base = os.path.splitext(os.path.basename(src))[0]
        if base == stem:
            return True
        if src.endswith(raw) or src.endswith(raw + ".md"):
            return True
    return False


def scan_wiki(wiki_root: str) -> dict:
    notes, sources, stems, md_files = _walk_wiki(wiki_root)
    dead_links: list[dict] = []
    referenced_sources: set[str] = set()
    pii_hits: list[dict] = []
    secret_hits: list[dict] = []

    def _scan_pii_secrets(rel: str, content: str, *, pii: bool) -> None:
        for m in _RE_SECRET.finditer(content):
            secret_hits.append({"note": rel, "match": m.group(0)[:12] + "..."})
        if not pii:
            return
        for m in _RE_EMAIL.finditer(content):
            val = m.group(0)
            if any(a in val.lower() for a in _ALLOW):
                continue
            pii_hits.append({"note": rel, "kind": "email", "value": val})
        for m in _RE_PHONE.finditer(content):
            val = re.sub(r"\s+", " ", m.group(0)).strip()
            compact = re.sub(r"\D", "", val)
            if any(
                re.sub(r"\D", "", a) in compact
                for a in _ALLOW
                if any(c.isdigit() for c in a)
            ):
                continue
            pii_hits.append({"note": rel, "kind": "phone", "value": val})
        for m in _RE_IBAN.finditer(content):
            pii_hits.append({"note": rel, "kind": "iban", "value": m.group(0)})

    # Wiki-Seiten: Links + PII. Sources: nur Secrets (Rohnotizen haben viele [[Klammern]]).
    for rel, full in notes.items():
        try:
            with open(full, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            continue

        for m in _RE_WIKI_LINK.finditer(content):
            target = m.group(1).strip()
            if not _link_live(target, stems, sources):
                dead_links.append({"source_note": rel, "target": target})
            else:
                t = target.replace("\\", "/")
                if t in sources:
                    referenced_sources.add(t)
                elif f"{t}.md" in sources:
                    referenced_sources.add(f"{t}.md")
                else:
                    stem = os.path.splitext(os.path.basename(t))[0]
                    for src in sources:
                        if os.path.splitext(os.path.basename(src))[0] == stem:
                            referenced_sources.add(src)

        for src in sources:
            src_name = os.path.basename(src)
            if src in content or src_name in content:
                referenced_sources.add(src)

        _scan_pii_secrets(rel, content, pii=True)

    for src_rel in sources:
        if not src_rel.endswith(".md"):
            continue
        full = os.path.join(wiki_root, src_rel)
        try:
            with open(full, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            continue
        _scan_pii_secrets(src_rel, content, pii=False)

    orphans = sorted(sources - referenced_sources)
    return {
        "total_notes": len(notes),
        "total_sources": len(sources),
        "dead_links_count": len(dead_links),
        "dead_links": dead_links[:20],
        "orphaned_sources_count": len(orphans),
        "orphaned_sources": orphans[:20],
        "_orphans": orphans,
        "pii_hits_count": len(pii_hits),
        "pii_hits": pii_hits[:20],
        "secret_hits_count": len(secret_hits),
        "secret_hits": secret_hits[:20],
        "_md_files": md_files,
    }


def _page_kind(rel: str) -> str:
    top = rel.split("/", 1)[0]
    return _KIND_BY_DIR.get(top, "source")


def _mtime_iso(path: str) -> str:
    try:
        ts = os.path.getmtime(path)
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
    except OSError:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _stub_page(rel: str, kind: str, touched: str) -> dict:
    stem = os.path.splitext(os.path.basename(rel))[0]
    slug = os.path.splitext(rel.replace("\\", "/"))[0].replace("/", ".")
    title = stem.replace("-", " ").replace("_", " ")
    return {
        "id": f"{kind}.{slug}",
        "title": title,
        "kind": kind,
        "path": rel.replace("\\", "/"),
        "aliases": [],
        "sourceIds": [],
        "questions": [],
        "contradictions": [],
        "bestUsedFor": [],
        "notEnoughFor": [],
        "relationshipCount": 0,
        "topRelationships": [],
        "pageType": kind,
        "freshnessLevel": "unknown",
        "lastTouchedAt": touched,
        "claimCount": 0,
        "topClaims": [],
    }


def rebuild_digest(wiki_root: str, md_files: list[tuple[str, str]]) -> dict:
    """Digest an den Dateibaum anpassen. Keine Wiki-Seiten löschen; Claims bleiben."""
    digest_path = os.path.join(wiki_root, DIGEST_REL)
    old: dict = {}
    if os.path.isfile(digest_path):
        try:
            with open(digest_path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                old = loaded
        except (OSError, json.JSONDecodeError):
            old = {}

    by_path: dict[str, dict] = {}
    for p in old.get("pages") or []:
        if isinstance(p, dict) and p.get("path"):
            by_path[str(p["path"]).replace("\\", "/")] = p

    pages = []
    seen = set()
    for rel, full in md_files:
        rel = rel.replace("\\", "/")
        seen.add(rel)
        kind = _page_kind(rel)
        touched = _mtime_iso(full)
        existing = by_path.get(rel)
        if isinstance(existing, dict):
            page = dict(existing)
            page["path"] = rel
            page["lastTouchedAt"] = touched
            if not page.get("kind"):
                page["kind"] = kind
            if not page.get("pageType"):
                page["pageType"] = page.get("kind") or kind
            pages.append(page)
        else:
            pages.append(_stub_page(rel, kind, touched))

    dropped = sorted(p for p in by_path if p not in seen)
    counts: dict[str, int] = {
        "entity": 0,
        "concept": 0,
        "source": 0,
        "synthesis": 0,
        "report": 0,
    }
    for p in pages:
        k = str(p.get("kind") or p.get("pageType") or "source")
        if k not in counts:
            counts[k] = 0
        counts[k] += 1

    out = {
        "pageCounts": counts,
        "claimCount": old.get("claimCount") or 0,
        "claimHealth": old.get("claimHealth")
        if isinstance(old.get("claimHealth"), dict)
        else {
            "freshness": {"fresh": 0, "aging": 0, "stale": 0, "unknown": 0},
            "contested": 0,
            "lowConfidence": 0,
            "missingEvidence": 0,
        },
        "contradictionClusters": old.get("contradictionClusters")
        if isinstance(old.get("contradictionClusters"), list)
        else [],
        "pages": pages,
        "generatedAt": datetime.now(TZ).isoformat(timespec="seconds"),
        "hygiene": {
            "pages_kept": len(pages),
            "pages_dropped_missing_file": len(dropped),
            "pages_added": sum(1 for rel, _ in md_files if rel.replace("\\", "/") not in by_path),
        },
    }
    os.makedirs(os.path.dirname(digest_path), exist_ok=True)
    tmp = digest_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, digest_path)
    return {
        "ok": True,
        "path": digest_path,
        "pages": len(pages),
        "dropped_missing_file": len(dropped),
        "added": out["hygiene"]["pages_added"],
    }


def _keep_file(rel: str) -> bool:
    r = (rel or "").replace("\\", "/").lstrip("/")
    base = os.path.basename(r).lower()
    if base in _KEEP_BASENAMES and "/" not in r:
        return True
    if base in _SKIP_FILES:
        return True
    return any(r.startswith(p) for p in _KEEP_PREFIXES)


def _iter_prefix_files(wiki_root: str, prefix: str):
    base = os.path.join(wiki_root, prefix)
    if not os.path.isdir(base):
        return
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".") and not d.startswith("_")]
        for name in files:
            if name.startswith("."):
                continue
            full = os.path.join(root, name)
            yield os.path.relpath(full, wiki_root).replace("\\", "/")


def plan_trash(wiki_root: str, scan: dict) -> list[str]:
    rels: set[str] = set()
    for prefix in ("summaries", "sources/grok-sessions"):
        rels.update(_iter_prefix_files(wiki_root, prefix))
    for rel in scan.get("_orphans") or scan.get("orphaned_sources") or []:
        rels.add(str(rel).replace("\\", "/"))
    _, sources, _, md_files = _walk_wiki(wiki_root)
    for rel in sources:
        if "unsafe-local-" in os.path.basename(rel).lower():
            rels.add(rel)
    for rel, _ in md_files:
        r = rel.replace("\\", "/")
        if r.startswith("summaries/") or r.startswith("sources/grok-sessions/"):
            rels.add(r)
        if r.startswith("sources/") and "unsafe-local-" in os.path.basename(r).lower():
            rels.add(r)
    return sorted(r for r in rels if r and not _keep_file(r))


def apply_trash(wiki_root: str, rels: list[str], day: str) -> int:
    moved = 0
    dest_root = os.path.join(wiki_root, TRASH_REL, day)
    for rel in rels:
        src = os.path.join(wiki_root, rel)
        if not os.path.isfile(src):
            continue
        dest = os.path.join(dest_root, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(dest):
            stem, ext = os.path.splitext(dest)
            n = 2
            while os.path.exists(f"{stem}-{n}{ext}"):
                n += 1
            dest = f"{stem}-{n}{ext}"
        shutil.move(src, dest)
        moved += 1
    for prefix in ("summaries", os.path.join("sources", "grok-sessions")):
        _rm_empty_tree(os.path.join(wiki_root, prefix))
    return moved


def _rm_empty_tree(path: str) -> None:
    if not os.path.isdir(path):
        return
    for dirpath, dirnames, filenames in os.walk(path, topdown=False):
        if not dirnames and not filenames:
            try:
                os.rmdir(dirpath)
            except OSError:
                pass
    if os.path.isdir(path) and not os.listdir(path):
        try:
            os.rmdir(path)
        except OSError:
            pass


def purge_trash(
    wiki_root: str, today: str, retention_days: int = RETENTION_DAYS
) -> int:
    root = os.path.join(wiki_root, TRASH_REL)
    if not os.path.isdir(root):
        return 0
    try:
        today_d = datetime.strptime(today, "%Y-%m-%d").date()
    except ValueError:
        today_d = datetime.now(TZ).date()
    cutoff = today_d - timedelta(days=retention_days)
    n = 0
    for name in os.listdir(root):
        full = os.path.join(root, name)
        if not os.path.isdir(full):
            continue
        try:
            d = datetime.strptime(name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d <= cutoff:
            shutil.rmtree(full, ignore_errors=True)
            n += 1
    return n


def fix_unique_dead_links(wiki_root: str) -> int:
    notes, sources, stems, _md = _walk_wiki(wiki_root)
    by_fold: dict[str, list[str]] = {}
    for s in stems:
        by_fold.setdefault(s.casefold(), []).append(s)
    n = 0
    for rel, full in notes.items():
        try:
            with open(full, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            continue
        new = content

        def repl(m: re.Match[str]) -> str:
            nonlocal n
            target = m.group(1).strip()
            if _link_live(target, stems, sources):
                return m.group(0)
            stem = os.path.splitext(os.path.basename(target))[0]
            hits = by_fold.get(stem.casefold()) or []
            if len(hits) != 1:
                return m.group(0)
            live = hits[0]
            if live == stem:
                return m.group(0)
            rest = m.group(0)[len("[[" + m.group(1)) :]
            n += 1
            return f"[[{live}{rest}"

        new = _RE_WIKI_LINK.sub(repl, content)
        if new != content:
            with open(full, "w", encoding="utf-8") as f:
                f.write(new)
    return n


def unwrap_links_to_trashed(wiki_root: str, trashed_rels: list[str]) -> int:
    stems = {
        os.path.splitext(os.path.basename(r))[0]
        for r in trashed_rels
        if r
    }
    trash_root = os.path.join(wiki_root, TRASH_REL)
    if os.path.isdir(trash_root):
        for root, dirs, files in os.walk(trash_root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                if name.endswith(".md"):
                    stems.add(os.path.splitext(name)[0])
    if not stems:
        return 0
    notes, _sources, _live, _md = _walk_wiki(wiki_root)
    n = 0
    for _rel, full in notes.items():
        try:
            with open(full, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            continue

        def repl(m: re.Match[str]) -> str:
            nonlocal n
            target = m.group(1).strip()
            stem = os.path.splitext(os.path.basename(target))[0]
            if stem not in stems:
                return m.group(0)
            alias = None
            raw = m.group(0)
            if "|" in raw:
                alias = raw.split("|", 1)[1].rstrip("]").strip()
            n += 1
            return alias or stem

        new = _RE_WIKI_LINK.sub(repl, content)
        if new != content:
            with open(full, "w", encoding="utf-8") as f:
                f.write(new)
    return n


def collapse_pending(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines(keepends=True)
    except OSError:
        return 0
    kept = [ln for ln in lines if not _PENDING_HYGIENE_RE.match(ln.rstrip("\n"))]
    if kept == lines:
        return 0
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(kept)
    return len(lines) - len(kept)


def write_hygiene_report(wiki_root: str, res: dict, day: str) -> str:
    reports = os.path.join(wiki_root, "reports")
    os.makedirs(reports, exist_ok=True)
    path = os.path.join(reports, "hygiene.md")
    trashed = list(res.get("trashed") or [])
    day_trash = os.path.join(wiki_root, TRASH_REL, day)
    if os.path.isdir(day_trash):
        on_disk = []
        for root, dirs, files in os.walk(day_trash):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                if name.startswith("."):
                    continue
                full = os.path.join(root, name)
                on_disk.append(os.path.relpath(full, day_trash).replace("\\", "/"))
        if on_disk:
            trashed = sorted(set(trashed) | set(on_disk))
    lines = [
        "---",
        "pageType: report",
        "id: report.hygiene",
        "title: Wiki-Hygiene",
        f"updatedAt: {day}",
        "---",
        "",
        "# Wiki-Hygiene",
        "",
        f"Stamp: {day}",
        f"Moved this run: {res.get('trashed_count', 0)}",
        f"In today's trash: {len(trashed)}",
        f"Purged trash dirs: {res.get('purged_count', 0)}",
        f"Dead links remaining: {res.get('dead_links_count', 0)}",
        f"Orphan sources remaining: {res.get('orphaned_sources_count', 0)}",
        f"PII: {res.get('pii_hits_count', 0)} | Secrets: {res.get('secret_hits_count', 0)}",
        f"Dead-link fixes: {res.get('dead_links_fixed', 0)}",
        "Salvage merken-Karten: 0 (Chat-Dumps / Red Line / trivial — Ordner weg)",
        "",
        "## Trashed (cap 40)",
        "",
    ]
    for rel in trashed[:40]:
        lines.append(f"- `{rel}`")
    if not trashed:
        lines.append("- (keine)")
    lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def run_hygiene(
    wiki_root: str,
    pending_path: str | None = None,
    day: str | None = None,
    apply: bool = True,
    no_digest: bool = False,
) -> dict:
    day = day or datetime.now(TZ).strftime("%Y-%m-%d")
    scan = scan_wiki(wiki_root)
    plan = plan_trash(wiki_root, scan)
    out = {
        "wiki_dir": wiki_root,
        "applied": False,
        "trashed": plan,
        "planned_count": len(plan),
        "trashed_count": 0,
        "purged_count": 0,
        "dead_links_fixed": 0,
        "day": day,
    }
    if apply:
        out["trashed_count"] = apply_trash(wiki_root, plan, day=day)
        out["purged_count"] = purge_trash(wiki_root, today=day)
        unwrapped = unwrap_links_to_trashed(wiki_root, plan)
        fixed = fix_unique_dead_links(wiki_root)
        out["dead_links_fixed"] = unwrapped + fixed
        if pending_path:
            collapse_pending(pending_path)
        scan = scan_wiki(wiki_root)
        out["applied"] = True
        out["trashed"] = plan
    out["dead_links_count"] = scan["dead_links_count"]
    out["orphaned_sources_count"] = scan["orphaned_sources_count"]
    out["pii_hits_count"] = scan["pii_hits_count"]
    out["secret_hits_count"] = scan["secret_hits_count"]
    out["total_notes"] = scan["total_notes"]
    out["total_sources"] = scan["total_sources"]
    md_files = scan.pop("_md_files", [])
    if apply:
        write_hygiene_report(wiki_root, out, day)
    digest_info = None
    if not no_digest:
        try:
            digest_info = rebuild_digest(wiki_root, md_files)
        except OSError as e:
            digest_info = {"ok": False, "error": str(e)}
    out["digest"] = digest_info
    out["timestamp"] = datetime.now(TZ).isoformat(timespec="seconds")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Glyph memory-wiki hygiene")
    p.add_argument("--json", action="store_true", help="JSON-Report")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="nur planen, nichts verschieben",
    )
    p.add_argument(
        "--no-digest",
        action="store_true",
        help="agent-digest.json nicht anfassen",
    )
    args = p.parse_args(argv)

    wiki_dir = _find_wiki_dir()
    if not wiki_dir:
        msg = "Wiki-Hygiene: memory-wiki Ordner nicht gefunden."
        if args.json:
            print(json.dumps({"error": "memory-wiki vault directory not found"}))
        else:
            print(msg)
        return 0

    res = run_hygiene(
        wiki_dir,
        pending_path=PENDING_CONTRACT,
        apply=not args.dry_run,
        no_digest=args.no_digest,
    )

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
        return 0

    digest_info = res.get("digest")
    digest_line = "Digest: übersprungen"
    if digest_info:
        if digest_info.get("ok"):
            digest_line = (
                f"Digest: {digest_info.get('pages', 0)} Seiten "
                f"(+{digest_info.get('added', 0)}, "
                f"stale-index {digest_info.get('dropped_missing_file', 0)})"
            )
        else:
            digest_line = f"Digest: Fehler {digest_info.get('error') or '?'}"

    mode = "dry-run" if args.dry_run else "apply"
    print(
        f"Wiki-Hygiene ({datetime.now(TZ).strftime('%Y-%m-%d %H:%M')} Europe/Berlin) [{mode}]\n"
        f"Pfad: {wiki_dir}\n"
        f"Seiten: {res['total_notes']} | Sources: {res['total_sources']}\n"
        f"Plan: {res.get('planned_count', 0)} | Moved: {res['trashed_count']} | "
        f"Purged: {res['purged_count']} | Link-Fixes: {res['dead_links_fixed']}\n"
        f"Dead Links: {res['dead_links_count']} | Orphan Sources: {res['orphaned_sources_count']}\n"
        f"PII Hits: {res['pii_hits_count']} | Secrets: {res['secret_hits_count']}\n"
        f"{digest_line}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
