# -*- coding: utf-8 -*-
"""
Runtime model config — hot-apply OpenRouter primary/fallback without process restart.

Source of truth for UI-driven changes is glyph-ui bindings; this module mutates
in-process config + the live provider so the next /chat uses the new IDs.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

from . import config
from . import llm
from .providers import factory


def _norm_id(value: Any) -> str:
    return str(value or "").strip()


def _norm_fallback(value: Any, *, present: bool) -> Optional[str]:
    """Empty string / whitespace → no fallback (None). Missing handled by caller."""
    if not present:
        return None
    s = _norm_id(value)
    return s or None


def current_models_snapshot() -> Dict[str, Any]:
    """Structured model state for /health and apply responses."""
    agent_primary = _norm_id(
        getattr(config, "AGENT_OPENROUTER_MODEL", None)
        or getattr(config, "OPENROUTER_MODEL", None)
    )
    agent_fb_raw = getattr(config, "AGENT_OPENROUTER_FALLBACK_MODEL", None)
    if agent_fb_raw is None:
        agent_fb_raw = getattr(config, "OPENROUTER_FALLBACK_MODEL", None)
    # Explicit empty string from hot-apply = no fallback (not "unset")
    agent_fb = _norm_id(agent_fb_raw) or None

    code_primary = _norm_id(getattr(config, "CODE_OPENROUTER_MODEL", None)) or agent_primary
    code_fb_raw = getattr(config, "CODE_OPENROUTER_FALLBACK_MODEL", None)
    if code_fb_raw is None and not hasattr(config, "CODE_OPENROUTER_FALLBACK_MODEL"):
        code_fb = agent_fb
    elif code_fb_raw is None:
        # attribute missing vs set to None
        code_fb = agent_fb
    else:
        code_fb = _norm_id(code_fb_raw) or None

    code_overrides = (
        code_primary != agent_primary
        or (code_fb or None) != (agent_fb or None)
    )

    p = None
    try:
        p = llm.get_provider()
    except Exception:
        p = None

    live_primary = _norm_id(getattr(p, "model", None)) if p else agent_primary
    live_fb = None
    if p is not None:
        live_fb = _norm_id(getattr(p, "fallback_model", None)) or None

    return {
        "shared": {
            "primary": agent_primary or live_primary,
            "fallback": agent_fb,
        },
        "code": {
            "primary": code_primary,
            "fallback": code_fb,
            "override": code_overrides,
        },
        "active": {
            "primary": live_primary or agent_primary,
            "fallback": live_fb if live_fb is not None else agent_fb,
            "provider": getattr(p, "provider_name", None) if p else None,
            "label": getattr(p, "model_name", None) if p else None,
        },
        "code_model": code_primary,
        "code_fallback_model": code_fb,
    }


def _set_env(name: str, value: Optional[str]) -> None:
    if value is None or value == "":
        # Keep key present as empty so code that reads env gets "no fallback"
        os.environ[name] = ""
    else:
        os.environ[name] = value


def apply_models(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Apply shared (+ optional code) model pair from a JSON body.

    Body shape:
      {
        "shared": { "primary": "...", "fallback": "" },
        "code":   { "primary": "", "fallback": "" }   # empty primary → use shared
      }

    Empty fallback ⇒ no fallback (None). Missing code block ⇒ code uses shared.
    """
    body = payload if isinstance(payload, dict) else {}
    shared = body.get("shared") if isinstance(body.get("shared"), dict) else {}
    # Flat shortcuts
    if not shared and body.get("primary"):
        shared = {
            "primary": body.get("primary"),
            "fallback": body.get("fallback"),
        }

    primary = _norm_id(shared.get("primary") or body.get("model"))
    if not primary:
        raise ValueError("shared.primary ist Pflicht (OpenRouter Model-ID)")

    # fallback key: if present (even empty) honor it; if absent keep previous? Spec: UI always sends.
    # Prefer explicit: if "fallback" in shared use it; elif top-level; else no fallback when applying full shared.
    if "fallback" in shared:
        fallback = _norm_fallback(shared.get("fallback"), present=True)
    elif "fallback" in body:
        fallback = _norm_fallback(body.get("fallback"), present=True)
    else:
        fallback = None

    code_in = body.get("code") if isinstance(body.get("code"), dict) else None
    if code_in is None or not _norm_id(code_in.get("primary")):
        code_primary = primary
        code_fallback = fallback
    else:
        code_primary = _norm_id(code_in.get("primary"))
        if "fallback" in code_in:
            code_fallback = _norm_fallback(code_in.get("fallback"), present=True)
        else:
            code_fallback = None

    # Mutate config module (code_loop / tool_loop read these)
    config.AGENT_OPENROUTER_MODEL = primary
    config.AGENT_OPENROUTER_FALLBACK_MODEL = fallback or ""
    config.OPENROUTER_MODEL = primary
    config.OPENROUTER_FALLBACK_MODEL = fallback or ""
    config.CODE_OPENROUTER_MODEL = code_primary
    config.CODE_OPENROUTER_FALLBACK_MODEL = code_fallback or ""

    _set_env("AGENT_OPENROUTER_MODEL", primary)
    _set_env("AGENT_OPENROUTER_FALLBACK_MODEL", fallback)
    _set_env("OPENROUTER_MODEL", primary)
    _set_env("OPENROUTER_FALLBACK_MODEL", fallback)
    _set_env("CODE_OPENROUTER_MODEL", code_primary)
    _set_env("CODE_OPENROUTER_FALLBACK_MODEL", code_fallback)

    # Live provider (agent/openrouter-chat path)
    try:
        p = llm.get_provider()
    except Exception:
        factory.reset_provider()
        p = llm.get_provider()

    if p is not None:
        p.model = primary
        p.fallback_model = fallback
        if hasattr(p, "_active_model"):
            p._active_model = primary
        if hasattr(p, "last_used"):
            p.last_used = None

    return current_models_snapshot()


def probe_model(model_id: str, timeout: int = 45) -> Dict[str, Any]:
    """
    Minimal OpenRouter chat with the given model id (production key/URL path).
    Does not permanently change the active model.
    """
    mid = _norm_id(model_id)
    if not mid:
        raise ValueError("model ist Pflicht")

    p = llm.get_provider()
    if getattr(p, "provider_name", "") not in ("openrouter", "fallback"):
        raise RuntimeError(f"Probe nur für OpenRouter, aktiv: {getattr(p, 'provider_name', '?')}")

    old_model = getattr(p, "model", None)
    old_fb = getattr(p, "fallback_model", None)
    old_active = getattr(p, "_active_model", None)
    old_last = getattr(p, "last_used", None)
    try:
        p.model = mid
        p.fallback_model = None  # probe exact model only
        if hasattr(p, "last_used"):
            p.last_used = None
        # Prefer raw completion to avoid free-fallback side effects
        if hasattr(p, "_chat_completion"):
            text = p._chat_completion(
                [
                    {"role": "system", "content": "Reply with exactly: ok"},
                    {"role": "user", "content": "ping"},
                ],
                temperature=0,
                timeout=timeout,
                model=mid,
            )
        else:
            text = p.chat(
                "Reply with exactly: ok",
                "ping",
                temperature=0,
                timeout=timeout,
            )
        return {
            "ok": True,
            "model": mid,
            "preview": (text or "")[:200],
        }
    finally:
        if old_model is not None:
            p.model = old_model
        p.fallback_model = old_fb
        if hasattr(p, "_active_model") and old_active is not None:
            p._active_model = old_active
        if hasattr(p, "last_used"):
            p.last_used = old_last
