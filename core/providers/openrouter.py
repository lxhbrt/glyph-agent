# -*- coding: utf-8 -*-
"""
OpenRouterProvider — Cloud-Modell über OpenRouter.

Kette (B+):
  1. Primär: config AGENT_OPENROUTER_MODEL (Default deepseek-v4-pro)
  2. Fallback: AGENT_OPENROUTER_FALLBACK_MODEL (Default deepseek/deepseek-v4-flash-0731)

Kein lokaler Chat-Fallback. Ohne API-Key: harter Fehler.

WICHTIG (Datenschutz):
Dieser Provider sendet den übergebenen Text an OpenRouter (Cloud).
Der Tool-Loop entscheidet, was hier ankommt — nur minimierte Ausschnitte,
nie der vollständige Vault. Key: OPENROUTER_API_KEY aus .env.

Timeout (Stabilität):
  Socket-Timeout allein reicht nicht — resp.read() kann hängen.
  _chat_completion erzwingt ein hartes Total-Timeout (Wall-Clock) per
  Worker-Thread + future.result(deadline), analog extract_tinyfish.
"""
import json
import logging
import os
import socket
import threading
import urllib.error
import urllib.request

from . import ModelProvider
from .. import log as _agent_log
from .. import config as _cfg

log = logging.getLogger("glyph-agent.openrouter")


def _message_text(data):
    """Finaler Antworttext aus einer Chat-Completions-Antwort."""
    msg = ((data or {}).get("choices") or [{}])[0].get("message") or {}
    content = msg.get("content")
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict):
                parts.append(str(p.get("text") or p.get("content") or ""))
            elif p is not None:
                parts.append(str(p))
        content = "".join(parts)
    text = str(content or "").strip()
    if text:
        return text
    return str(msg.get("reasoning_content") or "").strip()


def _resolve_chat_timeout(timeout=None):
    """Wall-Clock-Sekunden für einen OpenRouter-Chat-Call."""
    if timeout is not None:
        try:
            return max(1, int(timeout))
        except (TypeError, ValueError):
            pass
    mode = getattr(_cfg, "MODE", "agent") or "agent"
    if str(mode).lower() == "code":
        raw = getattr(_cfg, "CODE_CHAT_TIMEOUT", None)
    else:
        raw = getattr(_cfg, "CHAT_TIMEOUT", None)
    if raw is None:
        raw = getattr(_cfg, "CHAT_TIMEOUT", 60)
    try:
        return max(1, int(raw or 60))
    except (TypeError, ValueError):
        return 60


def _content_chars(content):
    """Zeichenzahl für Logging — str oder multimodal list (text + image_url)."""
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        n = 0
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                n += len(str(part.get("text") or ""))
            elif part.get("type") == "image_url":
                # Bild zählt pauschal (Base64 nicht voll mitzählen)
                n += 2000
        return n
    return len(str(content))


def user_content_with_images(text, images=None):
    """OpenAI multimodal user content: Text + optionale image_url-Parts.

    images: Liste von {type:'image_url', image_url:{url}} oder rohen
    {mime, data} / {mimeType, data}-Dicts.
    """
    text = text if text is not None else ""
    if not images:
        return text
    parts = []
    t = str(text).strip()
    if t:
        parts.append({"type": "text", "text": str(text)})
    else:
        parts.append({"type": "text", "text": "(Bild angehängt — bitte beschreiben/analysieren.)"})
    for img in images:
        if not isinstance(img, dict):
            continue
        if img.get("type") == "image_url" and isinstance(img.get("image_url"), dict):
            url = img["image_url"].get("url")
            if url:
                parts.append({"type": "image_url", "image_url": {"url": url}})
            continue
        mime = str(img.get("mime") or img.get("mimeType") or "image/png").lower()
        data = img.get("data") or img.get("content") or ""
        if not data:
            continue
        data = str(data).replace("data:" + mime + ";base64,", "")
        if str(data).startswith("data:"):
            # already a data URI
            parts.append({"type": "image_url", "image_url": {"url": str(data)}})
        else:
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{data}"},
            })
    return parts if len(parts) > 1 or (parts and parts[0].get("type") == "image_url") else (text or "")


class OpenRouterProvider(ModelProvider):
    def __init__(self, url=None, model=None, api_key=None, fallback_model=None):
        self.url = url or os.environ.get("OPENROUTER_URL", "https://openrouter.ai/api/v1")
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if getattr(_cfg, "MODE", "agent") == "agent":
            default_model = getattr(_cfg, "AGENT_OPENROUTER_MODEL", None) or os.environ.get(
                "AGENT_OPENROUTER_MODEL", "deepseek-v4-pro"
            )
        else:
            default_model = getattr(_cfg, "OPENROUTER_MODEL", None) or os.environ.get(
                "OPENROUTER_MODEL", "deepseek-v4-pro"
            )
        self.model = model or default_model
        # Fallback hinter dem Primärmodell (Direct/OR-Slug → OpenRouter Flash-0731).
        if fallback_model is not None:
            self.fallback_model = fallback_model or None
        elif getattr(_cfg, "MODE", "agent") == "agent":
            raw = getattr(_cfg, "AGENT_OPENROUTER_FALLBACK_MODEL", None)
            if raw is None:
                raw = os.environ.get(
                    "AGENT_OPENROUTER_FALLBACK_MODEL",
                    "deepseek/deepseek-v4-flash-0731",
                )
            self.fallback_model = raw or None
        else:
            raw = getattr(_cfg, "OPENROUTER_FALLBACK_MODEL", None)
            if raw is None:
                raw = os.environ.get(
                    "OPENROUTER_FALLBACK_MODEL",
                    "deepseek/deepseek-v4-flash-0731",
                )
            self.fallback_model = raw or None
        # openrouter | openrouter:free — für Trace / used_model
        self.last_used = None
        self._active_model = self.model

    @property
    def provider_name(self):
        return "openrouter"

    @property
    def model_name(self):
        # Aktuell genutztes Modell nach dem Turn; vorher die Kette.
        if self.last_used == "openrouter:free":
            return self.fallback_model or self.model
        if self.last_used == "openrouter":
            return self.model
        if self.fallback_model and self.fallback_model != self.model:
            return f"{self.model} → {self.fallback_model}"
        return self.model

    def _ensure_key(self):
        if not self.api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY nicht gesetzt (glyph-agent/.env). "
                "Cloud-Modell nicht verfügbar."
            )

    def _chat_completion(
        self, messages, temperature, timeout=None, model=None, url=None, api_key=None
    ):
        """Chat-Completions mit hartem Total-Timeout.

        urlopen(timeout=…) ist nur Socket-Timeout; resp.read() kann trotzdem
        hängen. Deshalb: Request im Worker, future.result(timeout=wall) bricht
        den Caller hart ab (Thread kann nachlaufen bis Socket-Timeout greift).
        url/api_key überschreiben den Provider-Default (Direct → OpenRouter-Hop).
        """
        use_key = (api_key if api_key is not None else self.api_key) or ""
        use_url = (url if url is not None else self.url) or ""
        if not use_key:
            self._ensure_key()
        m = model or self.model
        wall = _resolve_chat_timeout(timeout)
        total_chars = sum(_content_chars(x.get("content")) for x in messages)
        _agent_log.log(
            "cloud_send",
            provider=self.provider_name,
            model=m,
            chars=total_chars,
            n_messages=len(messages),
            timeout=wall,
        )
        payload = {
            "model": m,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        req = urllib.request.Request(
            f"{str(use_url).rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {use_key}",
            },
            method="POST",
        )

        box = {"data": None, "err": None}

        def _do_request():
            try:
                # Socket-Timeout ≤ Wall, damit der Worker nicht ewig nachläuft.
                with urllib.request.urlopen(req, timeout=wall) as resp:
                    raw = resp.read()
                box["data"] = json.loads(raw.decode("utf-8"))
            except Exception as e:
                box["err"] = e

        # Daemon-Thread: Total-Timeout per join(deadline); Prozess-Exit wartet nicht.
        # (ThreadPoolExecutor-Worker sind non-daemon und halten Tests/Shutdown auf.)
        worker = threading.Thread(
            target=_do_request,
            name=f"or-chat-{m[:24]}",
            daemon=True,
        )
        worker.start()
        worker.join(timeout=wall)
        if worker.is_alive():
            log.warning(
                "OpenRouter chat total-timeout nach %ss (model=%s)",
                wall, m,
            )
            try:
                _agent_log.log(
                    "cloud_timeout",
                    provider=self.provider_name,
                    model=m,
                    timeout=wall,
                )
            except Exception:
                pass
            raise TimeoutError(
                f"OpenRouter chat timeout nach {wall}s (model={m})"
            )

        if box["err"] is not None:
            e = box["err"]
            if isinstance(e, socket.timeout):
                raise TimeoutError(
                    f"OpenRouter chat timeout nach {wall}s (model={m}): {e}"
                ) from e
            if isinstance(e, urllib.error.URLError):
                reason = getattr(e, "reason", e)
                if isinstance(reason, socket.timeout) or "timed out" in str(e).lower():
                    raise TimeoutError(
                        f"OpenRouter chat timeout nach {wall}s (model={m}): {e}"
                    ) from e
            raise e

        data = box["data"] or {}
        return _message_text(data)

    def _with_free_fallback(self, messages, temperature, timeout=None):
        """Primär → Free. Setzt last_used / _active_model.
        Ohne API-Key kein Free-Versuch (gleicher Key, gleicher Fail)."""
        self._ensure_key()
        try:
            text = self._chat_completion(
                messages, temperature, timeout=timeout, model=self.model
            )
            self.last_used = "openrouter"
            self._active_model = self.model
            return text
        except Exception as e1:
            if not self.fallback_model or self.fallback_model == self.model:
                raise
            log.warning(
                "OpenRouter '%s' fehlgeschlagen (%s) — Free-Modell '%s'",
                self.model, e1, self.fallback_model,
            )
            text = self._chat_completion(
                messages, temperature, timeout=timeout, model=self.fallback_model
            )
            self.last_used = "openrouter:free"
            self._active_model = self.fallback_model
            return text.rstrip() + (
                f"\n\n_(OpenRouter: kostenloses Modell {self.fallback_model} verwendet.)_"
            )

    def generate(self, prompt, temperature=0.3, num_ctx=8192, timeout=None):
        return self._with_free_fallback(
            [{"role": "user", "content": prompt}], temperature, timeout=timeout
        )

    def chat(self, system, user, temperature=0.3, num_ctx=8192, timeout=None):
        """Chat. `user` darf str ODER multimodal list (text + image_url) sein."""
        return self._with_free_fallback(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature,
            timeout=timeout,
        )

    def chat_messages(self, messages, temperature=0.3, timeout=None):
        """Echte Multi-Turn-Messages (kein Flatten auf system+user)."""
        return self._with_free_fallback(
            list(messages or []), temperature, timeout=timeout
        )
