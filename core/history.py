# -*- coding: utf-8 -*-
"""Multi-Turn-Chat-Historie für POST /chat.

glyph-agent war pro Request zustandslos (nur aktuelle message). Dieser Modul
normalisiert und begrenzt den vom Client mitgelieferten Verlauf, damit
Nachfragen den vorherigen Turn kennen — ohne den Context zu sprengen.
"""
from __future__ import annotations

# ~12 Turns (user+assistant) — reicht für Produktvergleiche / Debugging.
MAX_HISTORY_MESSAGES = 24
# Budget nur für *prior* Turns (aktuelle Frage kommt extra).
MAX_HISTORY_CHARS = 60_000
# Einzelne Blase kappen (lange Agent-Antworten / Banner).
MAX_MSG_CHARS = 8_000

_ALLOWED_ROLES = frozenset({"user", "assistant"})


def normalize_prior_history(raw, current_message=None):
    """Liefert prior Turns als [{role, content}, ...] (ohne aktuelle User-Message).

    - nur user/assistant
    - leere Inhalte raus
    - trailing user-message, die der aktuellen message entspricht, wird verworfen
      (Client hat sie oft schon in history *und* als message)
    - von hinten begrenzen: max. MAX_HISTORY_MESSAGES und MAX_HISTORY_CHARS
    """
    if not raw:
        return []
    if not isinstance(raw, (list, tuple)):
        return []

    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role not in _ALLOWED_ROLES:
            continue
        content = item.get("content")
        if isinstance(content, list):
            # multimodal: nur Text-Parts
            parts = []
            for p in content:
                if isinstance(p, dict) and p.get("type") == "text":
                    t = str(p.get("text") or "").strip()
                    if t:
                        parts.append(t)
            content = "\n".join(parts)
        else:
            content = str(content or "").strip()
        if not content:
            continue
        if len(content) > MAX_MSG_CHARS:
            content = content[:MAX_MSG_CHARS] + "\n… [Nachricht gekürzt]"
        out.append({"role": role, "content": content})

    # Aktuelle User-Message nicht doppelt (Client push't oft vor dem Request).
    cur = (current_message or "").strip()
    if cur and out and out[-1]["role"] == "user":
        last = out[-1]["content"].strip()
        if last == cur or last.endswith(cur) or cur.endswith(last):
            out = out[:-1]

    # Von hinten: Message-Cap
    if len(out) > MAX_HISTORY_MESSAGES:
        out = out[-MAX_HISTORY_MESSAGES:]

    # Von hinten: Char-Cap (ältere Turns zuerst abwerfen)
    total = sum(len(m["content"]) for m in out)
    while out and total > MAX_HISTORY_CHARS:
        dropped = out.pop(0)
        total -= len(dropped["content"])

    return out


def format_prior_block(prior):
    """Kompakter Textblock für Final-Prompts / openrouter-chat."""
    if not prior:
        return ""
    lines = []
    for m in prior:
        label = "Nutzer" if m["role"] == "user" else "Assistent"
        lines.append(f"### {label}\n{m['content']}")
    return "\n\n".join(lines)


def build_history_for_loop(user_message, conversation_history=None):
    """prior + aktuelle user-message für Tool-Loops.

    Returns:
        (prior, history) — prior ohne current; history = prior + current user
    """
    prior = normalize_prior_history(conversation_history, current_message=user_message)
    history = list(prior) + [{"role": "user", "content": user_message}]
    return prior, history
