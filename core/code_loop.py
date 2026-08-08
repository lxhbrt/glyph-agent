# -*- coding: utf-8 -*-
"""
CODE-Modus-Loop (^_Code / C′).

DeepSeek V4 Flash über OpenRouter + Code-Tools (Read/Write/List/Run).
Kein VaultFind, kein Web-Precheck. Schreib-/Shell-Tools brauchen Confirm
(Glyph-Genehmigung über pending_confirmation + resume_token).
"""
from __future__ import annotations

import json
import secrets
import threading
import time

from . import config, llm, log, tool_registry
from . import code_tools

MAX_ROUNDS = getattr(config, "CODE_MAX_ROUNDS", 16) or 16

# Resume-State für Genehmigungen (In-Memory, Prozess-lokal)
_PENDING_LOCK = threading.Lock()
_PENDING = {}  # token -> state dict
_PENDING_TTL_S = 15 * 60


_CODE_ROLE = (
    "Du bist ^_Code: ein Code-Agent in Glyph. Denker: DeepSeek V4 Flash "
    f"({getattr(config, 'CODE_OPENROUTER_MODEL', 'deepseek/deepseek-v4-flash-0731')}) "
    "über OpenRouter.\n"
    "Du arbeitest NUR in konfigurierten Workspace-Roots "
    "(glyph-ui, glyph-agent, ~/.openclaw/workspace, …).\n"
    "Werkzeuge: ListDir, ReadFile (offset/limit), Grep, SearchReplace (exakt 1 Treffer), "
    "WriteFile (Diff+Backup), RunCommand (Whitelist).\n"
    "Regeln:\n"
    "- Antworte auf Deutsch; knapper Stil, präzise und handlungsorientiert.\n"
    "- STOP_SLOP: Kern zuerst, aktiv, konkret. Keine Floskeln "
    "(Gerne, Absolut, Zusammenfassend…, Es ist wichtig zu beachten, Als KI…, "
    "I hope this helps, Let’s dive in). Keine erfundenen Normen/Facts.\n"
    "- Bei kleinen Änderungen: Grep/ReadFile → SearchReplace (old muss exakt 1× vorkommen).\n"
    "- Bei großen/neuen Dateien: ReadFile → WriteFile mit komplettem Inhalt.\n"
    "- Shell nur für Tests/Status/Git (npm test, pytest, git status/add/commit/stash, "
    "ls, mkdir, …) — kein rm/sudo/push, keine destruktiven Befehle.\n"
    "- WriteFile, SearchReplace und RunCommand erfordern Nutzer-Genehmigung in Glyph.\n"
    "- Kein Vault, kein Obsidian, keine privaten Pfade außerhalb der Roots.\n"
    "- Bei Modell-Fragen: nenne DeepSeek V4 Flash und OpenRouter, Profil ^_Code.\n"
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


def _call_code_llm(messages, temperature=0.2, images=None):
    """OpenRouter-Chat mit CODE-Modell (temporärer Model-Swap am Provider).

    images: optionale OpenAI image_url-Parts (Vision). Viele Code-Modelle
    (DeepSeek Flash) unterstützen KEINE Vision — dann kommt ein klarer API-Fehler.
    """
    provider = llm.get_provider()
    # Mit Bildern: Vision-Modell (Luna), sonst DeepSeek CODE
    if images:
        primary = getattr(config, "CODE_VISION_MODEL", None) or getattr(
            config, "AGENT_OPENROUTER_MODEL", "openai/gpt-5.6-luna"
        )
        fallback = getattr(config, "AGENT_OPENROUTER_FALLBACK_MODEL", None)
    else:
        primary = getattr(config, "CODE_OPENROUTER_MODEL", "deepseek/deepseek-v4-flash-0731")
        fallback = getattr(config, "CODE_OPENROUTER_FALLBACK_MODEL", None)
    old_model = getattr(provider, "model", None)
    old_fb = getattr(provider, "fallback_model", None)
    try:
        provider.model = primary
        if fallback:
            provider.fallback_model = fallback
        # Flatten messages to system+user style when possible
        system_parts = []
        user_parts = []
        for m in messages:
            role = m.get("role")
            content = m.get("content") or ""
            if isinstance(content, list):
                content = "\n".join(
                    str(p.get("text") or "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            if role == "system":
                system_parts.append(content)
            else:
                user_parts.append(f"{role}: {content}" if role != "user" else content)
        system = "\n\n".join(system_parts) if system_parts else _CODE_ROLE
        if images:
            system = (
                system
                + "\nDu kannst angehängte Screenshots/Bilder SEHEN (Vision), "
                "falls das Modell es unterstützt. Nutze sie für UI-Bugs und Layout."
            )
        user = "\n\n".join(user_parts)
        # Datenschutz: CODE darf mehr Kontext (Diffs), aber Cap behalten
        max_chars = int(getattr(config, "EXTERNAL_MAX_CHARS", 4000) or 4000)
        # Für Code: höherer Default (16k), außer explizit 0=unbegrenzt
        code_cap = int(os_environ_int("CODE_EXTERNAL_MAX_CHARS", 16000))
        if code_cap > 0 and len(user) > code_cap:
            user = user[:code_cap] + "\n…[gekürzt]"
        # Hartes Total-Timeout (CODE_CHAT_TIMEOUT) — verhindert Einfrieren
        # wenn OpenRouter/DeepSeek nie zurückkehrt.
        chat_timeout = int(getattr(config, "CODE_CHAT_TIMEOUT", 60) or 60)
        if images:
            from .providers.openrouter import user_content_with_images
            user_payload = user_content_with_images(user, images)
        else:
            user_payload = user
        text = provider.chat(
            system, user_payload, temperature=temperature, timeout=chat_timeout
        )
        return text or ""
    finally:
        if old_model is not None:
            provider.model = old_model
        if old_fb is not None:
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
        "workspace_roots": list(getattr(config, "CODE_WORKSPACE_ROOTS", []) or []),
    }


def _tool_schema():
    return tool_registry.tool_schema_prompt(mode="code")


def _is_write_tool(name):
    t = tool_registry.tool_map(mode="code").get(name)
    return bool(t and t.get("write"))


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

    _emit({"type": "step", "action": tool_name, "status": "start",
           "detail": "nach Genehmigung" if allow_pending else "abgelehnt"})

    if allow_pending:
        # Einmalig freigeben
        def _confirm_once(tn, a):
            if tn == tool_name and a == args:
                return True
            if confirm is not None:
                return confirm(tn, a)
            return False
        result = tool_registry.execute(tool_name, args, confirm=_confirm_once, mode="code")
    else:
        result = {
            "ok": False,
            "result": None,
            "error": "Vom Nutzer in Glyph abgelehnt.",
        }

    _emit({
        "type": "step",
        "action": tool_name,
        "status": "done" if result.get("ok") else "error",
        "detail": (result.get("error") or "")[:80] or None,
    })
    tool_calls.append({"tool": tool_name, "args": args, "ok": result.get("ok")})
    tool_results.append({"tool": tool_name, "args": args, "result": result})
    steps.append({
        "step": tool_name,
        "status": "success" if result.get("ok") else "error",
        "detail": (result.get("error") or "")[:80] or None,
    })
    history.append({
        "role": "user",
        "content": (
            f"Tool-Ergebnis für '{tool_name}':\n"
            f"{json.dumps(result, ensure_ascii=False, default=str)}\n\n"
            "Wähle das nächste Tool (JSON) oder antworte auf Deutsch."
        ),
    })
    log.log("code_tool_resume", tool=tool_name, ok=result.get("ok"), allowed=allow_pending)

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
    while rounds < max_rounds:
        rounds += 1
        messages = [{"role": "system", "content": system}] + history
        _emit({
            "type": "step",
            "action": "OpenRouter",
            "status": "start",
            "detail": f"DeepSeek CODE ({model_name})",
        })
        try:
            reply = _call_code_llm(messages, images=images or None)
        except Exception as e:
            _emit({"type": "step", "action": "OpenRouter", "status": "error", "detail": str(e)[:80]})
            return {
                "ok": False,
                "answer": f"CODE-Denker fehlgeschlagen: {e}",
                "rounds": rounds,
                "tool_calls": tool_calls,
                "pending_confirmation": False,
                "trace": _build_trace(tool_calls, tool_results, steps=steps, model=model_name),
            }
        _emit({"type": "step", "action": "OpenRouter", "status": "done", "detail": None})
        _emit({"type": "answer", "status": "content", "text": reply})

        parsed = tool_registry.try_parse_tool_call(reply)
        if parsed is None:
            steps.append({"step": "answer", "status": "success", "detail": f"{len(reply)} Zeichen"})
            log.log("code_reply", rounds=rounds, direct=True, chars=len(reply or ""))
            try:
                p = llm.get_provider()
                active = getattr(p, "_active_model", None) or model_name
            except Exception:
                active = model_name
            return {
                "ok": True,
                "answer": (reply or "").strip(),
                "rounds": rounds,
                "tool_calls": tool_calls,
                "pending_confirmation": False,
                "trace": _build_trace(tool_calls, tool_results, steps=steps, model=active),
            }

        tool_name, args = parsed
        args = args or {}
        _emit({"type": "step", "action": tool_name, "status": "start", "detail": None})

        # Write/Shell: ohne Confirm → pending an Glyph
        if _is_write_tool(tool_name):
            allowed = False
            if confirm is not None:
                try:
                    allowed = bool(confirm(tool_name, args))
                except Exception:
                    allowed = False
            if not allowed:
                preview = code_tools.preview_for_confirm(tool_name, args)
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
                    "images": images,
                })
                _emit({
                    "type": "pending_confirmation",
                    "tool": tool_name,
                    "args": args,
                    "preview": preview,
                    "resume_token": token,
                })
                steps.append({
                    "step": tool_name,
                    "status": "pending",
                    "detail": "wartet auf Glyph-Genehmigung",
                })
                log.log("code_pending", tool=tool_name, token=token[:8])
                return {
                    "ok": True,
                    "answer": (
                        f"Freigabe nötig für **{tool_name}**.\n\n"
                        f"```\n{preview[:2000]}\n```\n\n"
                        "Bitte in Glyph erlauben oder ablehnen."
                    ),
                    "rounds": rounds,
                    "tool_calls": tool_calls,
                    "pending_confirmation": True,
                    "resume_token": token,
                    "pending": {
                        "tool": tool_name,
                        "args": args,
                        "preview": preview,
                    },
                    "trace": _build_trace(tool_calls, tool_results, steps=steps, model=model_name),
                }

        result = tool_registry.execute(tool_name, args, confirm=confirm, mode="code")
        _emit({
            "type": "step",
            "action": tool_name,
            "status": "done" if result.get("ok") else "error",
            "detail": (result.get("error") or "")[:80] or None,
        })
        tool_calls.append({"tool": tool_name, "args": args, "ok": result.get("ok")})
        tool_results.append({"tool": tool_name, "args": args, "result": result})
        steps.append({
            "step": tool_name,
            "status": "success" if result.get("ok") else "error",
            "detail": (result.get("error") or "")[:80] or None,
        })
        history.append({"role": "assistant", "content": reply})
        history.append({
            "role": "user",
            "content": (
                f"Tool-Ergebnis für '{tool_name}':\n"
                f"{json.dumps(result, ensure_ascii=False, default=str)}\n\n"
                "Wähle das nächste Tool (JSON) oder antworte auf Deutsch."
            ),
        })
        log.log("code_tool", tool=tool_name, rounds=rounds, ok=result.get("ok"))

        # Bei Hard-Error (Pfad/Whitelist) weiter dem Modell erklären lassen
        if not result.get("ok") and tool_name not in ("ReadFile", "ListDir"):
            # trotzdem nächste Runde erlauben (Modell kann korrigieren)
            pass

    steps.append({"step": "answer", "status": "error", "detail": "Runden-Limit"})
    return {
        "ok": False,
        "answer": "Zu viele Tool-Runden im CODE-Modus — gestoppt (Schleifenschutz).",
        "rounds": rounds,
        "tool_calls": tool_calls,
        "pending_confirmation": False,
        "trace": _build_trace(tool_calls, tool_results, steps=steps, model=model_name),
    }
