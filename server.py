#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
glyph-agent HTTP-Server — lokale Agenten- und Tool-Schicht als Dienst.

Bietet POST /chat an, damit der Glyph-ACP-Adapter (oder ein anderes Frontend)
die Tool-Orchestrierung nutzen kann, ohne die Agentenlogik selbst zu tragen.

  POST /chat   { "message": "...", "confirm": null }
               -> {"answer": str, "rounds": int, "tool_calls": [...], "ok": bool}

  GET  /health -> {"status": "ok", "provider": "...", "model": "..."}

Läuft standardmäßig auf 127.0.0.1:PORT (nur lokal). Keine externen Abhängigkeiten.
Enthält KEINE Bestätigungs-UI: für Schreib-Tools liefert der Server ein
"pending_confirmation"-Ergebnis bzw. lehnt ohne confirm ab (siehe tool_loop).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# .env früh laden (glyph-agent/.env), damit AGENT_PRIMARY_PROVIDER/OPENROUTER_MODEL/Keys
# unabhängig vom Startweg greifen (kein stiller Rückfall auf ollama).
try:
    from core.dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from core import config, tool_loop, llm

PORT = int(os.environ.get("GLYPH_AGENT_PORT", "18899"))
HOST = os.environ.get("GLYPH_AGENT_HOST", "127.0.0.1")

# --- Textanhänge (Stufe 1) ---
_ATTACH_TEXT_MIMES = {
    "text/plain", "text/markdown", "text/x-markdown", "text/html", "text/csv",
    "text/tab-separated-values", "application/json", "application/xml", "text/xml",
    "text/yaml", "application/yaml", "text/x-log",
}
_ATTACH_TEXT_EXTS = {"txt", "md", "markdown", "csv", "json", "xml", "yaml", "yml", "log", "html"}
_ATTACH_MAX_CHARS = 2 * 1024 * 1024  # pro Anhang


def _embed_attachments(message, attachments):
    """Bettet Textanhänge sicher in die Nachricht ein (rückwärtskompatibel).
    Nur Text-MIMEs/ext; Binär/Bild wird NICHT eingepackt (nur Hinweis).
    Liefert die (ggf. erweiterte) message."""
    import os
    if not attachments:
        return message or ""
    parts = [message] if (message and message.strip()) else []
    skipped = []
    for att in attachments or []:
        if not isinstance(att, dict):
            continue
        name = att.get("name") or "datei"
        # Dateiname escapen (nur Basisname, keine Kontrollzeichen)
        name = os.path.basename(str(name)).replace("\x00", "")[:200] or "datei"
        mime = str(att.get("mime") or "").lower()
        content = att.get("content") or ""
        ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
        is_text = mime in _ATTACH_TEXT_MIMES or (not mime and ext in _ATTACH_TEXT_EXTS) or (mime == "application/octet-stream" and ext in _ATTACH_TEXT_EXTS)
        if not is_text:
            skipped.append(f"{name} (kein erlaubter Text-Typ: {mime or 'unbekannt'})")
            continue
        if not str(content).strip():
            skipped.append(f"{name} (leer)")
            continue
        if len(str(content)) > _ATTACH_MAX_CHARS:
            raise ValueError(f"Textanhang zu groß: {name} (> {_ATTACH_MAX_CHARS} Zeichen)")
        parts.append(f"[Anhang: {name}]\n{content}\n[Ende Anhang: {name}]")
    if skipped:
        parts.append("[Übergangen (Stufe 1): " + "; ".join(skipped) + "]")
    return "\n\n".join(parts) if parts else (message or "")


def _handle_chat(payload):
    """Verarbeitet eine /chat-Anfrage.

    Modus-Unterscheidung (klar getrennt):
      - MODE=agent          : Tool-Loop mit Wiki-/Tool-Zugriff (Qwen lokal greift zu,
                              OpenRouter formuliert; Fallback-Kette).
      - MODE=openrouter-chat: reine Chat-Oberfläche OHNE Tools/Vault — nur OpenRouter.

    Optionales Feld "attachments": [{name, mime, content}, ...] (Textanhänge aus dem
    ACP-Adapter, Stufe 1). Rückwärtskompatibel — fehlt das Feld, bleibt alles wie bisher.
    """
    message = (payload or {}).get("message", "")
    attachments = (payload or {}).get("attachments")
    # Textanhänge in die Nachricht einbetten (deutlich gekennzeichnet),
    # damit das Modell den Inhalt als Kontext bekommt.
    message = _embed_attachments(message, attachments)
    if not message.strip():
        return {"ok": False, "answer": "Leere Nachricht.", "rounds": 0, "tool_calls": []}

    if getattr(config, "MODE", "agent") == "openrouter-chat":
        # Reiner OpenRouter-Chat: KEIN Tool-Loop, KEIN Vault, KEINE Tools.
        from core import llm as _llm
        system = (
            "Du bist ein hilfreicher Assistent (glyph-agent, reiner Chat-Modus). "
            "Du hast KEINEN Zugriff auf Dateien, einen Vault, Tools oder das Internet. "
            "Antworte nur aus deinem eigenen Wissen."
        )
        try:
            answer = _llm.chat(system, message)
            return {"ok": True, "answer": answer, "rounds": 1, "tool_calls": [], "chat_mode": "openrouter-chat"}
        except Exception as e:
            return {"ok": False, "answer": f"OpenRouter-Chat fehlgeschlagen: {e}", "rounds": 1, "tool_calls": [], "chat_mode": "openrouter-chat"}

    # Agentenmodus: kontrollierter Tool-Loop mit Bestätigung für Schreib-Tools.
    confirm_allow = (payload or {}).get("confirm")
    def confirm(tool_name, args):
        if not isinstance(confirm_allow, list):
            return False
        for c in confirm_allow:
            if isinstance(c, dict) and c.get("tool") == tool_name and c.get("args") == args:
                return True
        return False

    result = tool_loop.run(message, confirm=confirm)
    # Modell-Info anhängen (wichtig bei fallback: OpenRouter oder lokal geworden?).
    p = llm.get_provider()
    result = {"used_provider": p.provider_name, "used_model": p.model_name, "pending_confirmation": False, **result}
    return result


def _handle_health():
    p = llm.get_provider()
    return {"status": "ok", "provider": p.provider_name, "model": p.model_name}


def main():
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # leiser
            pass

        def _send(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health" or self.path.startswith("/health"):
                self._send(200, _handle_health())
            else:
                self._send(404, {"error": "Not found"})

        def do_POST(self):
            if self.path == "/chat" or self.path.startswith("/chat"):
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    payload = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    self._send(400, {"error": "Invalid JSON"})
                    return
                try:
                    result = _handle_chat(payload)
                    # bei write-Tool ohne Freigabe -> 200 mit pending-Flag
                    self._send(200, {"pending_confirmation": False, **result})
                except Exception as e:
                    self._send(500, {"error": str(e)})
            else:
                self._send(404, {"error": "Not found"})

    config.ensure_dirs()
    # Start-Validierung des Primär-Providers: Bei openrouter (Recherchepfad) NUR starten,
    # wenn der Key vorhanden ist — sonst klare Fehlermeldung statt stillem Fallback auf Qwen.
    try:
        provider = llm.get_provider()
    except Exception as e:
        print(f"❌ Provider-Initialisierung fehlgeschlagen: {e}", file=sys.stderr)
        sys.exit(1)
    if getattr(provider, "provider_name", "") in ("openrouter", "fallback"):
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not key:
            print(
                "❌ AGENT_PRIMARY_PROVIDER=openrouter erfordert OPENROUTER_API_KEY.\n"
                "   Start abgebrochen — KEIN stiller Fallback auf Qwen für den Recherchepfad.",
                file=sys.stderr,
            )
            sys.exit(1)
    server = HTTPServer((HOST, PORT), Handler)
    print(f"glyph-agent HTTP-Dienst läuft auf http://{HOST}:{PORT}")
    print(f"  Provider: {provider.provider_name}, Modell: {provider.model_name}")
    print("  POST /chat  |  GET /health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")
        server.server_close()


if __name__ == "__main__":
    main()
