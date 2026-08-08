# -*- coding: utf-8 -*-
"""
Kommunikations-Tools für den Agenten-Modus (MODE=agent).

  - MailList / MailRead: himalaya CLI (graceful wenn fehlt)
  - MessageSend: openclaw message send (write=True, Genehmigung in Glyph)

Kein freier Shell-String aus dem Modell — nur feste argv-Aufrufe.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

from . import log

_MAX_MAIL_CHARS = 30_000
_DEFAULT_TIMEOUT = 45


def _which(name, env_key=None, extra=()):
    cands = []
    if env_key:
        cands.append(os.environ.get(env_key))
    cands.extend(extra)
    cands.append(shutil.which(name))
    for cand in cands:
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def _himalaya_bin():
    return _which(
        "himalaya",
        "HIMALAYA_BIN",
        ("/opt/homebrew/bin/himalaya", "/usr/local/bin/himalaya"),
    )


def _openclaw_bin():
    return _which(
        "openclaw",
        "OPENCLAW_BIN",
        ("/opt/homebrew/bin/openclaw", "/usr/local/bin/openclaw"),
    )


def mail_list(folder="INBOX", query="", limit=20, account=None):
    """Listet Envelopes via himalaya. Read-only."""
    bin_path = _himalaya_bin()
    if not bin_path:
        log.log("mail_list_skipped", reason="himalaya_missing")
        return {
            "ok": False,
            "available": False,
            "envelopes": [],
            "error": "himalaya CLI nicht gefunden. Install: cargo/brew himalaya.",
        }

    limit = max(1, min(int(limit or 20), 100))
    folder = (folder or "INBOX").strip() or "INBOX"
    # himalaya hat kein -s Limit — wir schneiden clientseitig.
    argv = [bin_path, "-o", "json", "envelope", "list", "-f", folder]
    if account:
        argv.extend(["-a", str(account)])
    q = (query or "").strip()
    if q:
        argv.append(q)

    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=_DEFAULT_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "available": True,
            "envelopes": [],
            "error": f"himalaya Timeout nach {_DEFAULT_TIMEOUT}s",
        }
    except OSError as e:
        return {"ok": False, "available": True, "envelopes": [], "error": str(e)}

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:500]
        log.log("mail_list_error", error=err[:200])
        return {"ok": False, "available": True, "envelopes": [], "error": err or f"exit {proc.returncode}"}

    raw = (proc.stdout or "").strip()
    envelopes = []
    try:
        data = json.loads(raw) if raw else []
        if isinstance(data, list):
            envelopes = data[:limit]
        elif isinstance(data, dict):
            envelopes = (data.get("envelopes") or data.get("data") or [])[:limit]
    except json.JSONDecodeError:
        # plain fallback: rohe Zeilen
        envelopes = [{"raw": line} for line in raw.splitlines()[:limit] if line.strip()]

    log.log("mail_list", folder=folder, n=len(envelopes))
    return {
        "ok": True,
        "available": True,
        "folder": folder,
        "envelopes": envelopes,
        "count": len(envelopes),
        "error": None,
    }


def mail_read(msg_id, folder="INBOX", account=None, preview=True):
    """Liest eine Nachricht via himalaya message read. Read-only."""
    if msg_id is None or str(msg_id).strip() == "":
        raise ValueError("MailRead: id fehlt")
    bin_path = _himalaya_bin()
    if not bin_path:
        log.log("mail_read_skipped", reason="himalaya_missing")
        return {
            "ok": False,
            "available": False,
            "content": "",
            "error": "himalaya CLI nicht gefunden.",
        }

    folder = (folder or "INBOX").strip() or "INBOX"
    argv = [bin_path, "-o", "plain", "message", "read", "-f", folder, str(msg_id)]
    if preview:
        argv.append("--preview")
    if account:
        argv.extend(["-a", str(account)])

    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=_DEFAULT_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "available": True,
            "content": "",
            "error": f"himalaya Timeout nach {_DEFAULT_TIMEOUT}s",
        }
    except OSError as e:
        return {"ok": False, "available": True, "content": "", "error": str(e)}

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:500]
        log.log("mail_read_error", id=str(msg_id), error=err[:200])
        return {"ok": False, "available": True, "content": "", "error": err or f"exit {proc.returncode}"}

    text = proc.stdout or ""
    truncated = len(text) > _MAX_MAIL_CHARS
    text = text[:_MAX_MAIL_CHARS]
    log.log("mail_read", id=str(msg_id), chars=len(text))
    return {
        "ok": True,
        "available": True,
        "id": str(msg_id),
        "folder": folder,
        "content": text,
        "chars": len(text),
        "truncated": truncated,
        "error": None,
    }


def message_send(target, message, channel=None, account=None, dry_run=False):
    """
    Sendet Nachricht via openclaw message send.
    write=True-Tool: Confirm in Glyph/registry. Graceful wenn CLI/Gateway fehlt.
    """
    if not target or not str(target).strip():
        raise ValueError("MessageSend: target fehlt")
    if not message or not str(message).strip():
        raise ValueError("MessageSend: message fehlt")

    bin_path = _openclaw_bin()
    if not bin_path:
        log.log("message_send_skipped", reason="openclaw_missing")
        return {
            "ok": False,
            "available": False,
            "sent": False,
            "error": "openclaw CLI nicht gefunden.",
        }

    argv = [
        bin_path, "message", "send",
        "-t", str(target).strip(),
        "-m", str(message),
        "--json",
    ]
    if channel:
        argv.extend(["--channel", str(channel)])
    if account:
        argv.extend(["--account", str(account)])
    if dry_run:
        argv.append("--dry-run")

    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=_DEFAULT_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "available": True,
            "sent": False,
            "error": f"openclaw Timeout nach {_DEFAULT_TIMEOUT}s (Gateway erreichbar?)",
        }
    except OSError as e:
        return {"ok": False, "available": True, "sent": False, "error": str(e)}

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        msg = err or out or f"exit {proc.returncode}"
        log.log("message_send_error", error=msg[:200])
        return {
            "ok": False,
            "available": True,
            "sent": False,
            "error": msg[:800],
        }

    result = None
    if out:
        try:
            result = json.loads(out)
        except json.JSONDecodeError:
            result = {"raw": out[:2000]}

    log.log("message_send", target=str(target)[:80], channel=channel or "")
    return {
        "ok": True,
        "available": True,
        "sent": not dry_run,
        "target": str(target),
        "channel": channel,
        "result": result,
        "error": None,
    }
