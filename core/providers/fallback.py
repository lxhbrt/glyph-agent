# -*- coding: utf-8 -*-
"""
FallbackProvider — 2-stufige Cloud-Kette (Agentenmodus).

  1. bevorzugtes OpenRouter-Modell (Default: openai/gpt-5.6-luna)
  2. kostenloses OpenRouter-Modell (Default: inclusionai/ling-3.0-flash:free)

Kein lokaler Chat-Fallback. Wenn beide Cloud-Stufen scheitern: harter Fehler.
"""
import logging

from .. import config
from .openrouter import OpenRouterProvider

log = logging.getLogger("glyph-agent.fallback")


class FallbackProvider(OpenRouterProvider):
    def __init__(self, url=None, model=None, api_key=None, fallback_model=None):
        super().__init__(url, model, api_key)
        self.fallback_model = fallback_model or getattr(
            config, "AGENT_OPENROUTER_FALLBACK_MODEL", None
        ) or getattr(config, "OPENROUTER_FALLBACK_MODEL", self.model)
        # Letzter tatsächlich verwendeter Modus (openrouter | openrouter:free).
        self.last_used = None

    @property
    def provider_name(self):
        return "fallback"

    @property
    def model_name(self):
        return f"{self.model} → {self.fallback_model}"

    def _call(self, kind, args, kwargs):
        """Bevorzugtes OpenRouter → kostenloses OpenRouter. Setzt last_used."""
        try:
            text = self._cloud(kind, args, kwargs, self.model)
            self.last_used = "openrouter"
            return text, "openrouter"
        except Exception as e1:
            log.warning(
                "OpenRouter '%s' fehlgeschlagen (%s) — versuche kostenloses Modell",
                self.model, e1,
            )
            self.last_used = "openrouter:free"

        if self.fallback_model and self.fallback_model != self.model:
            try:
                text = self._cloud(kind, args, kwargs, self.fallback_model)
                self.last_used = "openrouter:free"
                return text, "openrouter:free"
            except Exception as e2:
                log.warning("OpenRouter '%s' fehlgeschlagen (%s)", self.fallback_model, e2)
                raise RuntimeError(
                    f"OpenRouter Primär ({self.model}) und Free ({self.fallback_model}) "
                    f"beide fehlgeschlagen: {e2}"
                ) from e2

        raise RuntimeError(
            f"OpenRouter '{self.model}' fehlgeschlagen und kein separates Free-Modell gesetzt."
        )

    def _cloud(self, kind, args, kwargs, model):
        if kind == "chat":
            system, user = args
            temperature = kwargs.get("temperature", 0.3)
            return self._chat_completion(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature,
                model=model,
            )
        prompt = args[0]
        temperature = kwargs.get("temperature", 0.3)
        return self._chat_completion(
            [{"role": "user", "content": prompt}], temperature, model=model
        )

    def _chat_completion(self, messages, temperature, timeout=60, model=None):
        self._ensure_key()
        m = model or self.model
        try:
            from .. import log as _al
            _al.log(
                "cloud_send",
                provider="openrouter",
                model=m,
                chars=sum(len(x.get("content", "")) for x in messages),
                n_messages=len(messages),
            )
        except Exception:
            pass
        import json
        import urllib.request
        payload = {
            "model": m,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        req = urllib.request.Request(
            f"{self.url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()

    def chat(self, system, user, temperature=0.3, num_ctx=8192):
        text, used = self._call("chat", (system, user), {"temperature": temperature})
        if used == "openrouter:free":
            text = text.rstrip() + (
                f"\n\n_(OpenRouter: kostenloses Modell {self.fallback_model} verwendet.)_"
            )
        return text

    def generate(self, prompt, temperature=0.3, num_ctx=8192):
        text, _used = self._call("generate", (prompt,), {"temperature": temperature})
        return text
