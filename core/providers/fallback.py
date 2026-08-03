# -*- coding: utf-8 -*-
"""
FallbackProvider — Agentenmodus-Fallback-Kette für OpenRouter + lokales Modell.

NUTZER-SPEZIFIKATION (getrennte Fallback-Ebenen, NUR im Agentenmodus):
  1. bevorzugtes OpenRouter-Modell
  2. kostenloses OpenRouter-Modell (Modellwechsel INNERHALB OpenRouter)
  3. lokales Qwen (nur wenn OpenRouter insgesamt nicht verfügbar)

Eigenschaften:
  - KEINE Endlosschleife: maximal 2 OpenRouter-Versuche (bevorzugt + gratis),
    dann 1 lokaler Versuch.
  - KEINE unbemerkte Datenübertragung: nur das, was der Tool-Loop übergibt,
    geht an OpenRouter; bei Fehler bleibt es lokal (Qwen), sendet nichts raus.
  - Der Vault verlässt über diesen Provider nie den Rechner als Ganzes —
    es kommen nur die vom Tool-Loop minimierten Ausschnitte an.
"""
import logging

from .. import config
from .ollama import OllamaProvider
from .openrouter import OpenRouterProvider

log = logging.getLogger("glyph-agent.fallback")


class FallbackProvider(OpenRouterProvider):
    def __init__(self, url=None, model=None, api_key=None,
                 fallback_model=None, local_fallback=None):
        super().__init__(url, model, api_key)
        self.fallback_model = fallback_model or getattr(
            config, "AGENT_OPENROUTER_FALLBACK_MODEL", self.model)
        self.local_fallback = local_fallback or OllamaProvider()
        # Letzter tatsächlich verwendeter Modus (openrouter | openrouter:free | local).
        # Wird vom Tool-Loop für den fallback_used-Trace ausgelesen (nie hartcodiert False).
        self.last_used = None

    @property
    def provider_name(self):
        return "fallback"

    @property
    def model_name(self):
        return f"{self.model} → {self.fallback_model} (lokal: {self.local_fallback.model_name})"

    def _call(self, kind, args, kwargs):
        """Versucht: bevorzugtes OpenRouter → kostenloses OpenRouter → lokal Qwen.
        Setzt self.last_used auf den tatsächlich verwendeten Modus."""
        # Stufe 1: bevorzugtes Modell.
        try:
            text = self._cloud(kind, args, kwargs, self.model)
            self.last_used = "openrouter"
            return text, "openrouter"
        except Exception as e1:
            log.warning("OpenRouter '%s' fehlgeschlagen (%s) — versuche kostenloses Modell",
                        self.model, e1)
            self.last_used = "openrouter:free"
        # Stufe 2: kostenloses OpenRouter-Modell.
        if self.fallback_model and self.fallback_model != self.model:
            try:
                text = self._cloud(kind, args, kwargs, self.fallback_model)
                self.last_used = "openrouter:free"
                return text, "openrouter:free"
            except Exception as e2:
                log.warning("OpenRouter '%s' fehlgeschlagen (%s)",
                            self.fallback_model, e2)
        else:
            log.warning("Kein separates kostenloses Modell — überspringe Stufe 2.")
        # Stufe 3: lokales Qwen (sendet NICHTS nach außen).
        fn = getattr(self.local_fallback, kind, None)
        if fn is None:
            raise RuntimeError("Kein lokaler Fallback verfügbar.")
        self.last_used = "local"
        return fn(*args, **kwargs), "local"

    def _cloud(self, kind, args, kwargs, model):
        # Konkret an OpenRouter gehen (nur minimaler Kontext des Tool-Loops).
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
        return self._chat_completion([{"role": "user", "content": prompt}], temperature, model=model)

    def _chat_completion(self, messages, temperature, timeout=60, model=None):
        """Nutzt das gegebene Modell (statt Konstruktor-Modell)."""
        self._ensure_key()
        m = model or self.model
        # Audit-Protokoll (welches Modell, wie viele Zeichen) — Datenschutz-Audit.
        try:
            from .. import log as _al
            _al.log("cloud_send", provider="openrouter", model=m,
                    chars=sum(len(x.get("content", "")) for x in messages),
                    n_messages=len(messages))
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
        if used == "local":
            text = text.rstrip() + (
                "\n\n_(OpenRouter war nicht erreichbar — Antwort lokal mit "
                f"{self.local_fallback.model_name} erstellt.)_"
            )
        elif used == "openrouter:free":
            text = text.rstrip() + (
                f"\n\n_(OpenRouter: kostenloses Modell {self.fallback_model} verwendet.)_"
            )
        return text

    def generate(self, prompt, temperature=0.3, num_ctx=8192):
        text, _used = self._call("generate", (prompt,), {"temperature": temperature})
        return text
