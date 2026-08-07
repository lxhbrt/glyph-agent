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
from core import code_loop

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


def _handle_chat(payload, send=None):
    """Verarbeitet eine /chat-Anfrage.

    send: optionaler Callback send(dict) for Live-Streaming. Wenn gesetzt, wird
          jede Stufe (z.B. VaultFind start/done, WebSearch, OpenRouter, Antwort-
          texte) als JSON-Line an send() übergeben, sobald sie eintritt — UND die
          finale Antwort am Ende. Fehlt send, wird alles blockierend berechnet
          und nur das Ergebnis-Dict zurückgegeben (rückwärtskompatibel).
    """
    message = (payload or {}).get("message", "")
    attachments = (payload or {}).get("attachments")
    # Textanhänge in die Nachricht einbetten (deutlich gekennzeichnet),
    # damit das Modell den Inhalt als Kontext bekommt.
    message = _embed_attachments(message, attachments)
    # Resume nach Glyph-Genehmigung darf ohne neue message laufen.
    is_resume = bool((payload or {}).get("resume_token"))
    if not message.strip() and not is_resume:
        err = {"ok": False, "answer": "Leere Nachricht.", "rounds": 0, "tool_calls": []}
        if send:
            send({"type": "done", **err})
        return err

    # Per-Request-Modus (C′): Payload.mode hat Vorrang; sonst Prozess-MODE.
    # "code" = ^_Code (DeepSeek + Workspace-Tools); Default = Vault-Agent.
    if (payload or {}).get("mode"):
        req_mode = str((payload or {}).get("mode")).lower()
    else:
        req_mode = str(getattr(config, "MODE", "agent") or "agent").lower()

    if req_mode == "openrouter-chat":
        # Reiner OpenRouter-Chat: KEIN Tool-Loop, KEIN Vault, KEINE Tools.
        from core import llm as _llm
        system = (
            "Du bist glyph-agent (reiner Chat-Modus). Cloud-Denker: "
            "openai/gpt-5.6-luna über OpenRouter (Free-Fallback bei Ausfall). "
            "Du hast KEINEN Zugriff auf Dateien, einen Vault, Tools oder das Internet. "
            "Antworte nur aus deinem eigenen Wissen. "
            "Bei Modell-Fragen: nenne openai/gpt-5.6-luna, kein Wiki/Tool nötig."
        )
        try:
            answer = _llm.chat(system, message)
            res = {"ok": True, "answer": answer, "rounds": 1, "tool_calls": [], "chat_mode": "openrouter-chat"}
            if send:
                send({"type": "done", **res})
            return res
        except Exception as e:
            res = {"ok": False, "answer": f"OpenRouter-Chat fehlgeschlagen: {e}", "rounds": 1, "tool_calls": [], "chat_mode": "openrouter-chat"}
            if send:
                send({"type": "done", **res})
            return res

    # Bestätigungsliste aus Payload (write-Tools / Shell).
    confirm_allow = (payload or {}).get("confirm")
    def confirm(tool_name, args):
        if not isinstance(confirm_allow, list):
            return False
        for c in confirm_allow:
            if isinstance(c, dict) and c.get("tool") == tool_name and c.get("args") == args:
                return True
        return False

    def on_event(event):
        if send:
            send(event)

    # --- CODE-Modus (^_Code): DeepSeek + Workspace-Tools, kein Vault ---
    if req_mode == "code":
        resume_token = (payload or {}).get("resume_token")
        allow_pending = (payload or {}).get("allow_pending")
        # allow_pending kann True/False sein; None = kein Resume
        if resume_token is not None and allow_pending is None and (payload or {}).get("allow") is not None:
            allow_pending = bool((payload or {}).get("allow"))
        result = code_loop.run_code(
            message,
            confirm=confirm,
            on_event=on_event,
            resume_token=resume_token,
            allow_pending=allow_pending,
        )
        p = llm.get_provider()
        used_model = (
            (result.get("trace") or {}).get("model")
            or getattr(config, "CODE_OPENROUTER_MODEL", None)
            or getattr(p, "_active_model", None)
            or p.model_name
        )
        result = {
            "used_provider": p.provider_name,
            "used_model": used_model,
            "mode": "code",
            **result,
        }
        if "pending_confirmation" not in result:
            result["pending_confirmation"] = False
        if send:
            send({"type": "done", **result})
        return result

    # Agentenmodus: kontrollierter Tool-Loop mit Bestätigung für Schreib-Tools.
    result = tool_loop.run(message, confirm=confirm, on_event=on_event)
    # Modell-Info anhängen (Primär Luna oder Free-Fallback).
    p = llm.get_provider()
    used_model = getattr(p, "_active_model", None) or p.model_name
    result = {
        "used_provider": p.provider_name,
        "used_model": used_model,
        "mode": "agent",
        "pending_confirmation": False,
        **result,
    }
    if send:
        send({"type": "done", **result})
    return result


def _handle_health():
    p = llm.get_provider()
    return {
        "status": "ok",
        "provider": p.provider_name,
        "model": p.model_name,
        "code_model": getattr(config, "CODE_OPENROUTER_MODEL", None),
        "modes": ["agent", "code", "openrouter-chat"],
    }


def main():
    # ThreadingHTTPServer: ein hängender /chat blockiert nicht /health und
    # andere Requests (Kern-Fix gegen Server-Einfrieren bei OpenRouter-Hang).
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
                    # Streaming-Modus (NDJSON): Client sendet explizit den Header —
                    # dann werden Stufen/Teil-Antworten live als JSON-Lines geflusht.
                    stream = (self.headers.get("Accept", "") == "application/x-ndjson")
                    if not stream:
                        result = _handle_chat(payload)
                        # bei write-Tool ohne Freigabe -> 200 mit pending-Flag
                        self._send(200, {"pending_confirmation": False, **result})
                        return
                    # --- NDJSON-Stream ---
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    def send(obj):
                        try:
                            line = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
                            self.wfile.write(line)
                            self.wfile.flush()
                        except Exception:
                            pass
                    _handle_chat(payload, send=send)
                except Exception as e:
                    if "stream" in locals() and stream:
                        try:
                            send({"type": "error", "error": str(e)})
                        except Exception:
                            pass
                    else:
                        self._send(500, {"error": str(e)})
            else:
                self._send(404, {"error": "Not found"})

    config.ensure_dirs()
    # Start-Validierung: OpenRouter-Key Pflicht — ohne Key kein Start (kein lokaler Chat).
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
                "   Start abgebrochen — Chat nur über OpenRouter (Luna → free).",
                file=sys.stderr,
            )
            sys.exit(1)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    # Daemon-Threads: Server-Stop wartet nicht auf hängende Chat-Worker.
    server.daemon_threads = True
    print(f"glyph-agent HTTP-Dienst läuft auf http://{HOST}:{PORT}")
    print(f"  Provider: {provider.provider_name}, Modell: {provider.model_name}")
    print(
        f"  Timeout: CHAT={getattr(config, 'CHAT_TIMEOUT', 60)}s "
        f"CODE={getattr(config, 'CODE_CHAT_TIMEOUT', 60)}s · threaded"
    )
    print("  POST /chat  |  GET /health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")
        server.server_close()


if __name__ == "__main__":
    main()
