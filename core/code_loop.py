# -*- coding: utf-8 -*-
"""
CODE-Modus-Loop (^_Code / C′).

DeepSeek V4 Flash über OpenRouter + Code-Tools (Read/Write/List/Run).
Kein VaultFind, kein Web-Precheck.
Write/Whitelist-Shell unter Workspace r+w ohne Popup; Elevated Shell
braucht Glyph-Genehmigung (pending_confirmation + resume_token).
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
)


def _shared_contract_snippet(max_chars=3200):
    """Gemeinsame Wahrheit Grok/Code/Agent — AGENTS + MEMORY unter ~/.glyph/"""
    import os as _os

    parts = []
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


def _call_code_llm(messages, temperature=0.2, images=None):
    """OpenRouter-Chat mit CODE-Modell (temporärer Model-Swap am Provider).

    images: optionale OpenAI image_url-Parts (Vision). Viele Code-Modelle
    (DeepSeek Flash) unterstützen KEINE Vision — dann kommt ein klarer API-Fehler.
    """
    provider = llm.get_provider()
    # Mit Bildern: Vision-Modell (Luna), sonst DeepSeek CODE
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
        # Empty/None fallback = no secondary model (UI may clear free fallback)
        provider.fallback_model = fallback if fallback else None
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


def _hard_fail_answer(tool_name, result):
    err = (result or {}).get("error") or "unbekannter Fehler"
    return (
        f"**Abbruch:** `{tool_name}` fehlgeschlagen.\n\n"
        f"{err}\n\n"
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

    # Hard-stop bei Fail nach Freigabe (sichtbarer Tiger-Tod)
    if not result.get("ok"):
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
        "content": (
            f"Tool-Ergebnis für '{tool_name}':\n"
            f"{json.dumps(result, ensure_ascii=False, default=str)}\n\n"
            "Wähle das nächste Tool (JSON) oder antworte auf Deutsch."
        ),
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

        parsed = tool_registry.try_parse_tool_call(reply)
        if parsed is None:
            # Nur echte Nutzerantworten streamen — nie Tool-JSON als Answer.
            answer = (reply or "").strip()
            if answer:
                _emit({"type": "answer", "status": "content", "text": answer})
            steps.append({"step": "answer", "status": "success", "detail": f"{len(answer)} Zeichen"})
            log.log("code_reply", rounds=rounds, direct=True, chars=len(answer))
            try:
                p = llm.get_provider()
                active = getattr(p, "_active_model", None) or model_name
            except Exception:
                active = model_name
            return {
                "ok": True,
                "answer": answer,
                "rounds": rounds,
                "tool_calls": tool_calls,
                "pending_confirmation": False,
                "trace": _build_trace(tool_calls, tool_results, steps=steps, model=active),
            }

        tool_name, args = parsed
        args = args or {}
        _emit({"type": "step", "action": tool_name, "status": "start", "detail": None})

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
                answer = _hard_fail_answer(tool_name, result)
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
                "content": (
                    f"Tool-Ergebnis für '{tool_name}':\n"
                    f"{json.dumps(result, ensure_ascii=False, default=str)}\n\n"
                    "Wähle das nächste Tool (JSON) oder antworte auf Deutsch."
                ),
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
                return {
                    "ok": True,
                    "answer": (
                        f"Freigabe nötig für **{tool_name}**"
                        + (f" — {risk}" if risk else "")
                        + f".\n\n```\n{preview[:2000]}\n```\n\n"
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
            "content": (
                f"Tool-Ergebnis für '{tool_name}':\n"
                f"{json.dumps(result, ensure_ascii=False, default=str)}\n\n"
                "Wähle das nächste Tool (JSON) oder antworte auf Deutsch."
            ),
        })
        log.log(
            "code_tool",
            tool=tool_name,
            rounds=rounds,
            ok=result.get("ok"),
            error=(result.get("error") or "")[:120] or None,
        )

        # Write/Shell-Fail: hard stop + Banner-fähig
        if not result.get("ok") and _is_write_tool(tool_name):
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
                "trace": _build_trace(
                    tool_calls, tool_results, steps=steps, model=model_name
                ),
            }

    steps.append({"step": "answer", "status": "error", "detail": "Runden-Limit"})
    return {
        "ok": False,
        "answer": "Zu viele Tool-Runden im CODE-Modus — gestoppt (Schleifenschutz).",
        "rounds": rounds,
        "tool_calls": tool_calls,
        "pending_confirmation": False,
        "trace": _build_trace(tool_calls, tool_results, steps=steps, model=model_name),
    }
