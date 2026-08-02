# -*- coding: utf-8 -*-
"""
FallbackProvider — Cloud-Modell (OpenRouter) mit stillem lokalen Fallback.

Resilienz + Datenschutz: Versucht zuerst OpenRouter. Schlägt das fehl
(kein Netz, kein Guthaben, API-Fehler, Timeout), wird AUTOMATISCH auf das
lokale Modell (Ollama/Qwen) zurückgefallen und der Wechsel gemeldet.

Wichtig:
  - KEINE Endlosschleife: pro Anfrage maximal EIN OpenRouter-Versuch.
  - KEINE unbemerkte Datenübertragung: nur das, was der Tool-Loop übergibt,
    geht an OpenRouter; bei Fehler bleibt es lokal (Qwen) und sendet nichts raus.
  - Der Vault verlässt über diesen Provider nie den Rechner als Ganzes —
    es kommen nur die vom Tool-Loop minimierten Ausschnitte an.
"""
import logging

from .ollama import OllamaProvider
from .openrouter import OpenRouterProvider

log = logging.getLogger("glyph-agent.fallback")


class FallbackProvider(OpenRouterProvider):
    def __init__(self, url=None, model=None, api_key=None, fallback=None):
        super().__init__(url, model, api_key)
        self.fallback = fallback or OllamaProvider()

    @property
    def provider_name(self):
        return "fallback"

    @property
    def model_name(self):
        # Anzeige: Cloud-Modell, mit Rückfall auf lokales Modell.
        return f"{self.model} (Fallback: {self.fallback.model_name})"

    def _call(self, kind, args, kwargs):
        """
        Versucht OpenRouter, fällt bei Fehler auf lokales Modell zurück.
        Liefert (text, used_provider).
        """
        try:
            text = self._cloud(kind, args, kwargs)
            return text, "openrouter"
        except Exception as e:
            log.warning("OpenRouter fehlgeschlagen (%s) — Fallback auf lokal %s: %s",
                        self.model, self.fallback.model_name, e)
            # Rückfall auf das lokale Modell — dies sendet NICHTS nach außen.
            fn = getattr(self.fallback, kind, None)
            if fn is None:
                raise
            return fn(*args, **kwargs), "local"

    def _cloud(self, kind, args, kwargs):
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
            )
        prompt = args[0]
        temperature = kwargs.get("temperature", 0.3)
        return self._chat_completion([{"role": "user", "content": prompt}], temperature)

    def chat(self, system, user, temperature=0.3, num_ctx=8192):
        text, used = self._call("chat", (system, user), {"temperature": temperature})
        if used == "local":
            # Dem Nutzer sichtbar machen, dass lokal beantwortet wurde.
            text = text.rstrip() + (
                "\n\n_(OpenRouter war nicht erreichbar — Antwort lokal mit "
                f"{self.fallback.model_name} erstellt.)_"
            )
        return text

    def generate(self, prompt, temperature=0.3, num_ctx=8192):
        text, used = self._call("generate", (prompt,), {"temperature": temperature})
        return text
