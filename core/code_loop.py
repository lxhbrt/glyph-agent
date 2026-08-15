# -*- coding: utf-8 -*-
"""
CODE-Modus-Loop (^_Code / C′).

DeepSeek V4 Flash (Direct) → OpenRouter Flash-0731 + Code-Tools (Read/Write/List/Run).
Kein VaultFind, kein Web-Precheck.
Write/Whitelist-Shell unter Workspace r+w ohne Popup; Elevated Shell
braucht Glyph-Genehmigung (pending_confirmation + resume_token).
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time

from . import config, llm, log, tool_registry
from . import code_tools

MAX_ROUNDS = getattr(config, "CODE_MAX_ROUNDS", 32) or 32

# Resume-State für Genehmigungen (In-Memory, Prozess-lokal)
_PENDING_LOCK = threading.Lock()
_PENDING = {}  # token -> state dict
_PENDING_TTL_S = 15 * 60


_CODE_ROLE = (
    "Du bist ^_Code: ein Code-Agent in Glyph. Denker: DeepSeek V4 Flash "
    f"({getattr(config, 'CODE_OPENROUTER_MODEL', 'deepseek-v4-flash')}) "
    "Direct, Fallback OpenRouter "
    f"{getattr(config, 'CODE_OPENROUTER_FALLBACK_MODEL', 'deepseek/deepseek-v4-flash-0731')}. "
    "Kein Tiny/Free.\n"
    "Du arbeitest NUR in Workspace-Roots aus `~/.glyph/workspaces.json` "
    "(Modes: r = lesen, r+w = lesen+schreiben+Shell, 🔒 private = tot).\n"
    "Werkzeuge: ListDir, ReadFile (offset/limit), Grep, SearchReplace (exakt 1 Treffer), "
    "WriteFile (Diff+Backup), RunCommand.\n"
    "Regeln:\n"
    "- Antworte auf Deutsch; knapper Stil, präzise und handlungsorientiert.\n"
    "- STOP_SLOP: Kern zuerst, aktiv, konkret. Keine Floskeln "
    "(Gerne, Absolut, Zusammenfassend…, Es ist wichtig zu beachten, Als KI…, "
    "I hope this helps, Let’s dive in). Keine erfundenen Normen/Facts.\n"
    "- Bei kleinen Änderungen: Grep/ReadFile → SearchReplace (old muss exakt 1× vorkommen).\n"
    "- Bei großen/neuen Dateien: ReadFile → WriteFile mit komplettem Inhalt.\n"
    "- WriteFile/SearchReplace unter Mode r+w: **ohne** Nutzer-Popup — einfach ausführen.\n"
    "- Shell Whitelist (git status/add/commit, npm test, pytest, ls, …) unter r+w: ohne Popup.\n"
    "- Elevated (git push/pull/fetch, Compound &&|;|, npm run service:*): Glyph fragt einmal.\n"
    "- Hart verboten: rm, sudo, Backticks, $() — auch nach Freigabe.\n"
    "- Bevorzuge EINEN Befehl pro RunCommand; Compound nur wenn nötig (dann Freigabe).\n"
    "- WAHRHEIT: Datei-Änderungen/Shell-Erfolge NUR behaupten, wenn das Tool-Ergebnis "
    "ok=true war. Ohne erfolgreichen Write/Replace/Command: ehrlich sagen, was fehlt "
    "(Fehler, Ablehnung, Timeout) — nie „erledigt“ erfinden.\n"
    "- Kein Vault, kein Obsidian, keine privaten Pfade außerhalb der Roots.\n"
    "- Bei Modell-Fragen: nenne DeepSeek V4 Flash und OpenRouter, Profil ^_Code.\n"
    "- SHARED SoT: `~/.glyph/AGENTS.md` gilt auch für dich (Jobs/Vaults/Skills/Red Line) — "
    "nicht im Chat neu verhandeln, was dort und in Repo-CONTEXT geklärt ist.\n"
    "- KORREKTUR: Chat vs. AGENTS/CONTEXT → Konflikt nennen, Vertrag gewinnt. "
    "Vorschlag nach ~/.glyph/memory/pending-contract.md, nicht nur in den Chat. "
    "AGENTS/MEMORY nur nach Auftrag. Repo-Verhalten → CONTEXT.md.\n"
    "- ORIENT: Orient+System map der r+w-Workspaces liegen im System-Prompt. "
    "Kein Blind-Walk (ListDir/Grep über den ganzen Tree). Gezielt die genannten Quellen. "
    "Map veraltet → nach Struktur-Change dort nachziehen, nicht parallele Doku erfinden.\n"
)


def _shared_contract_snippet(max_chars=3200):
    """Gemeinsame Wahrheit Grok/Code/Agent — AGENTS + MEMORY unter ~/.glyph/"""
    import os as _os

    parts = []
    try:
        from . import vault_tools as _vt

        pending = _vt.pending_contract_prompt_block(max_body=800)
    except Exception:
        pending = None
    if pending:
        parts.append(pending)
    for path, label, cap in (
        (_os.path.expanduser("~/.glyph/AGENTS.md"), "SHARED SoT · AGENTS.md", 2000),
        (_os.path.expanduser("~/.glyph/MEMORY.md"), "MEMORY (Lektionen)", 1600),
    ):
        if not _os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                body = f.read().strip()
        except OSError:
            continue
        if not body:
            continue
        if len(body) > cap:
            body = body[: cap - 20] + "\n…[gekürzt]"
        parts.append(f"### {label}\n{body}")
    if not parts:
        return ""
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[: max_chars - 20] + "\n…[gekürzt]"
    return (
        "\n\nSHARED (~/.glyph — befolgen, nicht neu verhandeln):\n" + text
    )


def _purge_stale_pending():
    now = time.time()
    with _PENDING_LOCK:
        dead = [k for k, v in _PENDING.items() if now - v.get("ts", 0) > _PENDING_TTL_S]
        for k in dead:
            _PENDING.pop(k, None)


def _save_pending(state):
    _purge_stale_pending()
    token = secrets.token_hex(12)
    state = dict(state)
    state["ts"] = time.time()
    with _PENDING_LOCK:
        _PENDING[token] = state
    return token


def _pop_pending(token):
    with _PENDING_LOCK:
        return _PENDING.pop(token, None)


def _content_len(content):
    if content is None:
        return 0
    if isinstance(content, list):
        n = 0
        for p in content:
            if isinstance(p, dict):
                n += len(str(p.get("text") or ""))
        return n
    return len(str(content))


def _messages_chars(messages):
    return sum(_content_len(m.get("content")) for m in messages or [])


def extract_orient_map(md, max_chars=2800):
    """## Orient + ## System map bis zur nächsten anderen ##-Überschrift."""
    if not md:
        return ""
    lines = str(md).splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## ") and "orient" in line.lower():
            start = i
            break
    if start is None:
        return ""
    out = []
    seen_map = False
    for i in range(start, len(lines)):
        line = lines[i]
        if i > start and line.startswith("## "):
            title = line[3:].strip().lower()
            if title.startswith("system map") or title.startswith("system-map"):
                seen_map = True
            elif seen_map or not title.startswith("orient"):
                break
        out.append(line)
    text = "\n".join(out).strip()
    if max_chars > 0 and len(text) > max_chars:
        text = text[: max_chars - 20] + "\n…[gekürzt]"
    return text


def workspace_orient_block():
    """r+w: Orient+Map. r: eine Zeile. 🔒 aus."""
    try:
        from . import workspaces_registry as wr
        items = wr.list_workspaces(include_missing=False)
    except Exception:
        return ""
    parts = []
    for w in items:
        if not w.get("enabled"):
            continue
        mode = w.get("mode") or "r"
        if mode == "private":
            continue
        name = w.get("name") or w.get("id") or "?"
        path = w.get("path") or ""
        if mode != "rw":
            parts.append(f"- {name} ({path}) — mode r, CONTEXT nicht injiziert.")
            continue
        ctx = os.path.join(path, "CONTEXT.md") if path else ""
        body = ""
        if ctx and os.path.isfile(ctx):
            try:
                with open(ctx, encoding="utf-8", errors="replace") as f:
                    body = extract_orient_map(f.read())
            except OSError:
                body = ""
        if body:
            parts.append(f"### {name} ({path}) r+w\n{body}")
        else:
            parts.append(f"- {name} ({path}) — r+w, kein CONTEXT.md Orient/Map.")
    if not parts:
        return ""
    return (
        "\n\nWORKSPACE-ORIENT (injiziert — nicht den Tree walken):\n"
        + "\n\n".join(parts)
    )


def _tool_result_summary(tool_name, result):
    """Kurzer History-Eintrag statt vollem JSON-Dump, damit der Verlauf schlank bleibt.
    Schwergewichtige Erfolge (ReadFile/SearchReplace/WriteFile) werden zusammengefasst;
    Fehler und kompakte Treffer (Grep/ListDir) bleiben voll, da kurz und wichtig."""
    ok = bool(result and result.get("ok"))
    err = str((result or {}).get("error") or "").strip()
    if not ok:
        # Fehler voll behalten (Selbstkorrektur braucht den Kontext)
        return (
            f"Tool-Ergebnis für '{tool_name}':\n"
            f"{json.dumps(result, ensure_ascii=False, default=str)}\n\n"
            "Wähle das nächste Tool (JSON) oder antworte auf Deutsch."
        )
    if tool_name in ("ReadFile",):
        body = (result.get("result") or {})
        if isinstance(body, dict):
            text = body.get("content") or body.get("text") or ""
            chars = body.get("chars") or len(text)
            head = str(text)[:400]
            return (
                f"Tool-Ergebnis für 'ReadFile' ({body.get('path') or ''}, ~{chars} Zeichen):\n"
                f"```\n{head}...\n```\n"
                "(Gekürzt. Bei Bedarf mit ReadFile + offset gezielt weiterlesen.)\n"
                "Wähle das nächste Tool (JSON) oder antworte auf Deutsch."
            )
    if tool_name in ("SearchReplace", "WriteFile"):
        body = (result.get("result") or {})
        if isinstance(body, dict):
            summary = (
                f"Schreiben OK → {body.get('path') or '?'} "
                f"({body.get('old_chars') or 0}→{body.get('new_chars') or 0} Zeichen)"
            )
            return (
                f"Tool-Ergebnis für '{tool_name}':\n{summary}\n\n"
                "Wähle das nächste Tool (JSON) oder antworte auf Deutsch."
            )
    # Standard: bleibt wie bisher
    return (
        f"Tool-Ergebnis für '{tool_name}':\n"
        f"{json.dumps(result, ensure_ascii=False, default=str)}\n\n"
        "Wähle das nächste Tool (JSON) oder antworte auf Deutsch."
    )


def trim_code_history(history, budget):
    """Älteste Turns weg. Erstes User + letztes Tool-Ergebnis bleiben."""
    history = list(history or [])
    if not history or budget <= 0:
        return history
    if _messages_chars(history) <= budget:
        return history
    first = history[0]
    last = history[-1]
    if len(history) == 1:
        return history
    middle = history[1:-1]
    kept = [first] + middle + [last]
    while len(kept) > 2 and _messages_chars(kept) > budget:
        # ältesten Turn nach dem ersten User droppen
        kept.pop(1)
        if len(kept) > 2 and kept[1].get("role") == "assistant":
            # dangling assistant ohne vorherigen user-tool: ok, nächste Runde
            pass
    if _messages_chars(kept) > budget and len(kept) > 2:
        kept = [first, last]
    return kept


def repeat_tool_key(tool_name, args):
    args = args or {}
    if tool_name == "Grep":
        return (
            "Grep",
            str(args.get("pattern") or ""),
            str(args.get("path") or "."),
            bool(args.get("case_insensitive")),
        )
    if tool_name == "ListDir":
        return (
            "ListDir",
            str(args.get("path") or "."),
            bool(args.get("recursive")),
        )
    return None


def is_retryable_write_fail(tool_name, result):
    err = str((result or {}).get("error") or "")
    if tool_name != "SearchReplace":
        return False
    return (
        "0 Treffer" in err
        or "old-String nicht gefunden" in err
        or ("kommt" in err and "Treffer" in err)
    )


def should_hard_stop(tool_name, result):
    """Hart tot: Deny/🔒/Nutzer-Ablehnung/Shell-Timeout. SearchReplace-Treffer nicht."""
    err = str((result or {}).get("error") or "")
    payload = (result or {}).get("result")
    if not isinstance(payload, dict):
        payload = {}
    low = err.lower()
    if "vom nutzer" in low and "abgelehnt" in low:
        return True
    if "private" in low or "🔒" in err:
        return True
    if tool_name == "RunCommand" and payload.get("timeout"):
        return True
    if is_retryable_write_fail(tool_name, result):
        return False
    return False


def pick_test_command(root):
    import os as _os
    if not root or not _os.path.isdir(root):
        return None
    if _os.path.isfile(_os.path.join(root, "package.json")):
        return "npm test"
    if (
        _os.path.isfile(_os.path.join(root, "pytest.ini"))
        or _os.path.isfile(_os.path.join(root, "pyproject.toml"))
        or _os.path.isdir(_os.path.join(root, "tests"))
    ):
        return "pytest"
    return None


def run_workspace_tests(roots, _emit=None):
    """Whitelist-Test je beschriebenem Root. Kein service:*."""
    import os as _os
    seen = set()
    for root in roots or []:
        try:
            real = _os.path.realpath(root)
        except OSError:
            continue
        if real in seen or not _os.path.isdir(real):
            continue
        seen.add(real)
        cmd = pick_test_command(real)
        if not cmd:
            continue
        label = _os.path.basename(real.rstrip(_os.sep)) or real
        if _emit:
            _emit({
                "type": "step",
                "action": "RunCommand",
                "status": "start",
                "detail": f"Test {cmd} · {label}",
            })
        try:
            res = code_tools.run_command(cmd, cwd=real, timeout=120, allow_elevated=False)
        except Exception as e:
            if _emit:
                _emit({
                    "type": "step",
                    "action": "RunCommand",
                    "status": "error",
                    "detail": str(e)[:200],
                })
            return {
                "ok": False,
                "error": f"{cmd} in {label}: {e}",
                "root": real,
                "command": cmd,
            }
        if res.get("timeout") or int(res.get("exit_code") or 0) != 0:
            tail = (res.get("stderr") or res.get("stdout") or "Test fehlgeschlagen")[:400]
            if _emit:
                _emit({
                    "type": "step",
                    "action": "RunCommand",
                    "status": "error",
                    "detail": tail[:200],
                })
            return {
                "ok": False,
                "error": f"{cmd} in {label} exit {res.get('exit_code')}: {tail}",
                "root": real,
                "command": cmd,
            }
        if _emit:
            _emit({
                "type": "step",
                "action": "RunCommand",
                "status": "done",
                "detail": f"{cmd} ok · {label}",
            })
    return {"ok": True}


def _call_code_llm(messages, temperature=0.2, images=None):
    """CODE-Denker: echte messages[], Trim ältester Turns, letztes Tool bleibt.

    images: optionale OpenAI image_url-Parts (Vision). Viele Code-Modelle
    (DeepSeek Flash) unterstützen KEINE Vision — dann kommt ein klarer API-Fehler.
    """
    provider = llm.get_provider()
    if images:
        primary = getattr(config, "CODE_VISION_MODEL", None) or "openai/gpt-5.6-luna"
        fallback = getattr(config, "AGENT_OPENROUTER_FALLBACK_MODEL", None)
    else:
        primary = getattr(config, "CODE_OPENROUTER_MODEL", "deepseek/deepseek-v4-flash-0731")
        fallback = getattr(config, "CODE_OPENROUTER_FALLBACK_MODEL", None)
    old_model = getattr(provider, "model", None)
    old_fb = getattr(provider, "fallback_model", None)
    try:
        provider.model = primary
        provider.fallback_model = fallback if fallback else None
        payload = []
        for m in messages or []:
            payload.append({
                "role": m.get("role") or "user",
                "content": m.get("content") or "",
            })
        if not payload:
            payload = [{"role": "system", "content": _CODE_ROLE}]
        if payload[0].get("role") == "system" and images:
            payload[0]["content"] = (
                str(payload[0].get("content") or "")
                + "\nDu kannst angehängte Screenshots/Bilder SEHEN (Vision), "
                "falls das Modell es unterstützt. Nutze sie für UI-Bugs und Layout."
            )
        budget = int(getattr(config, "CODE_MESSAGE_CHARS", 64000) or 0)
        if budget > 0:
            sys_msgs = [m for m in payload if m.get("role") == "system"]
            hist = [m for m in payload if m.get("role") != "system"]
            reserved = _messages_chars(sys_msgs)
            hist_budget = max(4000, budget - reserved)
            hist = trim_code_history(hist, hist_budget)
            payload = sys_msgs + hist
        if images:
            from .providers.openrouter import user_content_with_images
            for m in payload:
                if m.get("role") == "user":
                    text = m.get("content") or ""
                    if isinstance(text, list):
                        text = "\n".join(
                            str(p.get("text") or "")
                            for p in text
                            if isinstance(p, dict) and p.get("type") == "text"
                        )
                    m["content"] = user_content_with_images(text, images)
                    break
        chat_timeout = int(getattr(config, "CODE_CHAT_TIMEOUT", 180) or 180)
        if hasattr(provider, "chat_messages"):
            text = provider.chat_messages(
                payload, temperature=temperature, timeout=chat_timeout
            )
        else:
            # Ältere Provider: letzter User + System (kein Flatten-Cap am Schwanz)
            system = "\n\n".join(
                str(m.get("content") or "")
                for m in payload
                if m.get("role") == "system"
            )
            last_user = ""
            for m in reversed(payload):
                if m.get("role") == "user":
                    last_user = m.get("content") or ""
                    break
            text = provider.chat(
                system, last_user, temperature=temperature, timeout=chat_timeout
            )
        return text or ""
    finally:
        provider.model = old_model
        provider.fallback_model = old_fb


def os_environ_int(name, default):
    import os
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _build_trace(tool_calls, tool_results=None, steps=None, model=None):
    try:
        provider = llm.get_provider()
        pname = getattr(provider, "provider_name", "openrouter")
        mname = model or getattr(provider, "_active_model", None) or getattr(
            config, "CODE_OPENROUTER_MODEL", "?"
        )
    except Exception:
        pname, mname = "openrouter", model or "?"
    result_by_tool = {}
    for tr in tool_results or []:
        result_by_tool[tr.get("tool")] = tr.get("result") or {}
    meta = []
    for tc in tool_calls or []:
        result = result_by_tool.get(tc.get("tool")) or {}
        payload = result.get("result")
        rlen = 0
        if payload is not None:
            try:
                rlen = len(str(payload))
            except Exception:
                rlen = 0
        meta.append({
            "tool": tc.get("tool"),
            "status": "success" if tc.get("ok") else "error",
            "result_length": rlen,
            "error": result.get("error"),
        })
    return {
        "provider": pname,
        "model": mname,
        "mode": "code",
        "fallback_used": False,
        "tool_calls": meta,
        "steps": list(steps or []),
        "request_id": "local-code",
        "workspace_roots": list(code_tools.workspace_roots() or []),
    }


def _tool_schema():
    return tool_registry.tool_schema_prompt(mode="code")


def _is_write_tool(name):
    t = tool_registry.tool_map(mode="code").get(name)
    return bool(t and t.get("write"))


def _auto_confirm(_tool_name, _args):
    """Bereits durch Policy freigegeben — execute-Callback."""
    return True


def _hard_fail_answer(tool_name, result, args=None):
    err = (result or {}).get("error") or "unbekannter Fehler"
    extra = ""
    # Bei abgelehnten Shell-Befehlen den konkreten Befehl sichtbar machen,
    # damit der Abbruch nachvollziehbar ist statt stumm zu scheitern.
    if tool_name == "RunCommand" and isinstance(args, dict):
        cmd = args.get("command") or args.get("cmd") or ""
        cwd = args.get("cwd") or "."
        if cmd:
            extra = f"\n\nAbgelehnter Befehl:\n```\n{cmd}\n```\nin: `{cwd}`"
    return (
        f"**Abbruch:** `{tool_name}` fehlgeschlagen.\n\n"
        f"{err}{extra}\n\n"
        "Kette gestoppt — bitte korrigieren und erneut senden."
    )


def run_code(
    user_message,
    confirm=None,
    max_rounds=None,
    on_event=None,
    resume_token=None,
    allow_pending=None,
    images=None,
    conversation_history=None,
):
    """
    CODE-Tool-Loop.

    confirm: Callback(tool_name, args) -> bool  (Whitelist-Freigaben im selben Request)
    resume_token + allow_pending: Fortsetzen nach Glyph-Genehmigung
      allow_pending True  = freigegeben ausführen
      allow_pending False = abgelehnt, Modell informieren
    images: optionale OpenAI image_url-Parts (Vision / Screenshots)
    conversation_history: optionale prior Turns für Multi-Turn-Nachfragen
    """
    def _emit(event):
        if on_event is None:
            return
        try:
            on_event(event)
        except Exception:
            pass

    max_rounds = int(max_rounds or MAX_ROUNDS)
    images = list(images or [])

    # --- Resume nach Genehmigung ---
    if resume_token:
        state = _pop_pending(resume_token)
        if not state:
            return {
                "ok": False,
                "answer": "Genehmigungs-Token ungültig oder abgelaufen. Bitte Anfrage neu senden.",
                "rounds": 0,
                "tool_calls": [],
                "pending_confirmation": False,
                "trace": _build_trace([], steps=[{"step": "resume", "status": "error"}]),
            }
        return _continue_from_state(
            state, allow_pending=bool(allow_pending), confirm=confirm,
            max_rounds=max_rounds, on_event=on_event, _emit=_emit,
        )

    from . import history as chat_history

    prior_history, history = chat_history.build_history_for_loop(
        user_message, conversation_history
    )
    if prior_history:
        try:
            from . import log as _log
            _log.log(
                "code_history",
                prior_msgs=len(prior_history),
                prior_chars=sum(len(m["content"]) for m in prior_history),
            )
        except Exception:
            pass

    system = (
        _CODE_ROLE
        + _shared_contract_snippet()
        + workspace_orient_block()
        + "\n\n"
        + _tool_schema()
        + "\n\nWICHTIG: Wenn du ein Werkzeug brauchst, antworte NUR mit JSON "
        '{"tool": Name, "args": {...}}. Kein Text drumherum. '
        "Wenn KEIN Werkzeug nötig ist, antworte normal auf Deutsch."
        + (
            "\nMulti-Turn: Chat-Verlauf liegt vor. Bei Nachfragen darauf aufbauen "
            "(Dateipfade, Vereinbarungen, vorherige Schritte) — nicht von null starten."
            if prior_history
            else ""
        )
    )
    tool_calls = []
    tool_results = []
    steps = []
    rounds = 0
    model_name = getattr(config, "CODE_OPENROUTER_MODEL", "deepseek/deepseek-v4-flash-0731")
    if prior_history:
        steps.append({
            "step": "history",
            "status": "success",
            "detail": f"{len(prior_history)} prior msg(s)",
        })
    if images:
        steps.append({"step": "Vision", "status": "success", "detail": f"{len(images)} Bild(er)"})
        _emit({
            "type": "step",
            "action": "Vision",
            "status": "start",
            "detail": f"{len(images)} Bild(er) — braucht Vision-fähiges CODE-Modell",
        })

    return _loop(
        system=system,
        history=history,
        tool_calls=tool_calls,
        tool_results=tool_results,
        steps=steps,
        rounds=rounds,
        user_message=user_message,
        confirm=confirm,
        max_rounds=max_rounds,
        _emit=_emit,
        model_name=model_name,
        images=images,
    )


def _continue_from_state(state, allow_pending, confirm, max_rounds, on_event, _emit):
    tool_name = state["pending_tool"]
    args = state["pending_args"]
    history = state["history"]
    system = state["system"]
    tool_calls = state["tool_calls"]
    tool_results = state["tool_results"]
    steps = state["steps"]
    rounds = state["rounds"]
    user_message = state["user_message"]
    model_name = state.get("model_name") or getattr(
        config, "CODE_OPENROUTER_MODEL", "deepseek/deepseek-v4-flash-0731"
    )
    elevated = bool(state.get("elevated"))

    _emit({"type": "step", "action": tool_name, "status": "start",
           "detail": "nach Genehmigung" if allow_pending else "abgelehnt"})

    if allow_pending:
        # Einmalig freigeben (Elevated → allow_elevated=True)
        def _confirm_once(tn, a):
            if tn == tool_name and a == args:
                return True
            if confirm is not None:
                return confirm(tn, a)
            return False
        result = tool_registry.execute(
            tool_name,
            args,
            confirm=_confirm_once,
            mode="code",
            allow_elevated=elevated,
        )
    else:
        result = {
            "ok": False,
            "result": None,
            "error": "Vom Nutzer in Glyph abgelehnt.",
        }

    err_detail = (result.get("error") or "")[:200] or None
    _emit({
        "type": "step",
        "action": tool_name,
        "status": "done" if result.get("ok") else "error",
        "detail": err_detail,
    })
    tool_calls.append({"tool": tool_name, "args": args, "ok": result.get("ok")})
    tool_results.append({"tool": tool_name, "args": args, "result": result})
    steps.append({
        "step": tool_name,
        "status": "success" if result.get("ok") else "error",
        "detail": err_detail,
    })
    log.log(
        "code_tool_resume",
        tool=tool_name,
        ok=result.get("ok"),
        allowed=allow_pending,
        elevated=elevated,
        error=(result.get("error") or "")[:120] or None,
    )

    # Nach Freigabe: Deny/Timeout hart; SearchReplace-Treffer zurück in die Loop
    if not result.get("ok") and should_hard_stop(tool_name, result):
        answer = _hard_fail_answer(tool_name, result)
        _emit({"type": "answer", "status": "content", "text": answer})
        return {
            "ok": False,
            "answer": answer,
            "rounds": rounds,
            "tool_calls": tool_calls,
            "pending_confirmation": False,
            "hard_error": True,
            "error": result.get("error") or f"{tool_name} fehlgeschlagen",
            "trace": _build_trace(tool_calls, tool_results, steps=steps, model=model_name),
        }

    history.append({
        "role": "user",
        "content": _tool_result_summary(tool_name, result),
    })

    return _loop(
        system=system,
        history=history,
        tool_calls=tool_calls,
        tool_results=tool_results,
        steps=steps,
        rounds=rounds,
        user_message=user_message,
        confirm=confirm,
        max_rounds=max_rounds,
        _emit=_emit,
        model_name=model_name,
        images=list(state.get("images") or []),
    )


def _loop(
    system,
    history,
    tool_calls,
    tool_results,
    steps,
    rounds,
    user_message,
    confirm,
    max_rounds,
    _emit,
    model_name,
    images=None,
):
    images = list(images or [])
    written_roots = set()
    repeat_counts = {}

    def _finish(answer, *, ok=True, hard=False, error=None):
        if written_roots:
            tres = run_workspace_tests(list(written_roots), _emit=_emit)
            if not tres.get("ok"):
                fail = _hard_fail_answer(
                    "RunCommand",
                    {"error": tres.get("error") or "Test fehlgeschlagen"},
                )
                _emit({"type": "answer", "status": "content", "text": fail})
                steps.append({
                    "step": "RunCommand",
                    "status": "error",
                    "detail": (tres.get("error") or "")[:200],
                })
                return {
                    "ok": False,
                    "answer": fail,
                    "rounds": rounds,
                    "tool_calls": tool_calls,
                    "pending_confirmation": False,
                    "hard_error": True,
                    "error": tres.get("error"),
                    "trace": _build_trace(
                        tool_calls, tool_results, steps=steps, model=model_name
                    ),
                }
        if answer:
            _emit({"type": "answer", "status": "content", "text": answer})
        return {
            "ok": ok,
            "answer": answer or "",
            "rounds": rounds,
            "tool_calls": tool_calls,
            "pending_confirmation": False,
            "hard_error": bool(hard),
            "error": error,
            "trace": _build_trace(
                tool_calls, tool_results, steps=steps, model=model_name
            ),
        }

    while rounds < max_rounds:
        rounds += 1
        messages = [{"role": "system", "content": system}] + history
        _emit({
            "type": "step",
            "action": "OpenRouter",
            "status": "start",
            "detail": llm.thinker_step_detail("code", model=model_name),
        })
        try:
            reply = _call_code_llm(messages, images=images or None)
        except Exception as e:
            _emit({"type": "step", "action": "OpenRouter", "status": "error", "detail": str(e)[:80]})
            err_answer = f"CODE-Denker fehlgeschlagen: {e}"
            _emit({"type": "answer", "status": "content", "text": err_answer})
            return {
                "ok": False,
                "answer": err_answer,
                "rounds": rounds,
                "tool_calls": tool_calls,
                "pending_confirmation": False,
                "trace": _build_trace(tool_calls, tool_results, steps=steps, model=model_name),
            }
        _emit({"type": "step", "action": "OpenRouter", "status": "done", "detail": None})

        parsed = tool_registry.try_parse_tool_call(reply)
        if parsed is None:
            # Nur echte Nutzerantworten streamen — nie Tool-JSON/DSML als Answer.
            if tool_registry.looks_like_dsml(reply):
                prose = tool_registry.prose_before_dsml(reply)
                answer = prose or (
                    "Denker hat einen Tool-Call im DSML-Format geschickt, "
                    "der sich nicht lesen ließ. Bitte die Anfrage nochmal senden."
                )
            else:
                answer = (reply or "").strip()
            steps.append({"step": "answer", "status": "success", "detail": f"{len(answer)} Zeichen"})
            log.log("code_reply", rounds=rounds, direct=True, chars=len(answer))
            try:
                p = llm.get_provider()
                active = getattr(p, "_active_model", None) or model_name
            except Exception:
                active = model_name
            model_name = active
            return _finish(answer, ok=True)

        tool_name, args = parsed
        args = args or {}
        _emit({"type": "step", "action": tool_name, "status": "start", "detail": None})

        rkey = repeat_tool_key(tool_name, args)
        if rkey is not None:
            repeat_counts[rkey] = repeat_counts.get(rkey, 0) + 1
            if repeat_counts[rkey] >= 3:
                result = {
                    "ok": False,
                    "result": None,
                    "error": (
                        "Gleicher Grep/ListDir zum 3. Mal. "
                        "CONTEXT-Map nutzen oder auf Deutsch antworten — nicht weiter walken."
                    ),
                }
                err_detail = result["error"][:200]
                _emit({
                    "type": "step",
                    "action": tool_name,
                    "status": "error",
                    "detail": err_detail,
                })
                tool_calls.append({"tool": tool_name, "args": args, "ok": False})
                tool_results.append({"tool": tool_name, "args": args, "result": result})
                steps.append({
                    "step": tool_name,
                    "status": "error",
                    "detail": err_detail,
                })
                history.append({"role": "assistant", "content": reply})
                history.append({
                    "role": "user",
                    "content": _tool_result_summary(tool_name, result),
                })
                log.log("code_tool", tool=tool_name, rounds=rounds, ok=False, repeat=True)
                continue

        # Policy: allow | confirm (elevated) | deny
        decision = code_tools.permission_decision(tool_name, args)
        action = decision.get("action") or "deny"

        if action == "deny":
            result = {
                "ok": False,
                "result": None,
                "error": decision.get("reason") or "abgelehnt",
            }
            err_detail = (result.get("error") or "")[:200]
            _emit({
                "type": "step",
                "action": tool_name,
                "status": "error",
                "detail": err_detail,
            })
            tool_calls.append({"tool": tool_name, "args": args, "ok": False})
            tool_results.append({"tool": tool_name, "args": args, "result": result})
            steps.append({
                "step": tool_name,
                "status": "error",
                "detail": err_detail,
            })
            log.log("code_tool", tool=tool_name, rounds=rounds, ok=False, denied=True)
            # Write/Shell-Deny: hard stop; Read-Tools: Modell darf korrigieren
            if _is_write_tool(tool_name):
                answer = _hard_fail_answer(tool_name, result, args)
                _emit({"type": "answer", "status": "content", "text": answer})
                return {
                    "ok": False,
                    "answer": answer,
                    "rounds": rounds,
                    "tool_calls": tool_calls,
                    "pending_confirmation": False,
                    "hard_error": True,
                    "error": result.get("error"),
                    "trace": _build_trace(
                        tool_calls, tool_results, steps=steps, model=model_name
                    ),
                }
            history.append({"role": "assistant", "content": reply})
            history.append({
                "role": "user",
                "content": _tool_result_summary(tool_name, result),
            })
            continue

        if action == "confirm":
            # Optional: Payload-confirm-Liste (API) kann sofort erlauben
            allowed = False
            if confirm is not None:
                try:
                    allowed = bool(confirm(tool_name, args))
                except Exception:
                    allowed = False
            if not allowed:
                preview = decision.get("preview") or code_tools.preview_for_confirm(
                    tool_name, args
                )
                risk = decision.get("risk") or decision.get("reason") or ""
                history.append({"role": "assistant", "content": reply})
                token = _save_pending({
                    "history": history,
                    "system": system,
                    "tool_calls": tool_calls,
                    "tool_results": tool_results,
                    "steps": steps,
                    "rounds": rounds,
                    "user_message": user_message,
                    "pending_tool": tool_name,
                    "pending_args": args,
                    "model_name": model_name,
                    "preview": preview,
                    "elevated": bool(decision.get("elevated")),
                    "risk": risk,
                    "images": images,
                })
                _emit({
                    "type": "pending_confirmation",
                    "tool": tool_name,
                    "args": args,
                    "preview": preview,
                    "elevated": bool(decision.get("elevated")),
                    "risk": risk,
                    "resume_token": token,
                })
                steps.append({
                    "step": tool_name,
                    "status": "pending",
                    "detail": (risk or "wartet auf Glyph-Genehmigung")[:80],
                })
                log.log(
                    "code_pending",
                    tool=tool_name,
                    token=token[:8],
                    elevated=bool(decision.get("elevated")),
                )
                # Primärspur = Status (Vertrauen: kein stilles Warten ohne Text).
                status_answer = (
                    f"Freigabe nötig für **{tool_name}**"
                    + (f" — {risk}" if risk else "")
                    + f".\n\n```\n{preview[:2000]}\n```\n\n"
                    "Bitte in Glyph erlauben oder ablehnen."
                )
                _emit({"type": "answer", "status": "content", "text": status_answer})
                return {
                    "ok": True,
                    "answer": status_answer,
                    "rounds": rounds,
                    "tool_calls": tool_calls,
                    "pending_confirmation": True,
                    "resume_token": token,
                    "pending": {
                        "tool": tool_name,
                        "args": args,
                        "preview": preview,
                        "elevated": bool(decision.get("elevated")),
                        "risk": risk,
                    },
                    "trace": _build_trace(
                        tool_calls, tool_results, steps=steps, model=model_name
                    ),
                }

        # action == allow (oder confirm + payload-confirm)
        result = tool_registry.execute(
            tool_name,
            args,
            confirm=_auto_confirm,
            mode="code",
            allow_elevated=bool(decision.get("elevated")),
        )
        err_detail = (result.get("error") or "")[:200] or None
        _emit({
            "type": "step",
            "action": tool_name,
            "status": "done" if result.get("ok") else "error",
            "detail": err_detail,
        })
        tool_calls.append({"tool": tool_name, "args": args, "ok": result.get("ok")})
        tool_results.append({"tool": tool_name, "args": args, "result": result})
        steps.append({
            "step": tool_name,
            "status": "success" if result.get("ok") else "error",
            "detail": err_detail,
        })
        history.append({"role": "assistant", "content": reply})
        history.append({
            "role": "user",
            "content": _tool_result_summary(tool_name, result),
        })
        log.log(
            "code_tool",
            tool=tool_name,
            rounds=rounds,
            ok=result.get("ok"),
            error=(result.get("error") or "")[:120] or None,
        )

        if result.get("ok") and tool_name in ("WriteFile", "SearchReplace"):
            payload = result.get("result") if isinstance(result.get("result"), dict) else {}
            root = payload.get("root")
            if root:
                written_roots.add(root)

        if should_hard_stop(tool_name, result):
            answer = _hard_fail_answer(tool_name, result)
            return _finish(answer, ok=False, hard=True, error=result.get("error"))

    steps.append({"step": "answer", "status": "error", "detail": "Runden-Limit"})
    limit_msg = "Zu viele Tool-Runden im CODE-Modus — gestoppt (Schleifenschutz)."
    return _finish(limit_msg, ok=False, error="Runden-Limit")
