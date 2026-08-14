# -*- coding: utf-8 -*-
"""
Stabilität: hartes Total-Timeout für OpenRouter-Chat + ThreadingHTTPServer.

Regression gegen ^_Code-Einfrieren:
  - hängender resp.read() / urlopen muss nach Wall-Clock abbrechen
  - während eines hängenden /chat muss GET /health weiter antworten
"""
import json
import os
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from urllib import request as urllib_request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.providers.openrouter import OpenRouterProvider, _resolve_chat_timeout
from core import config


class ResolveTimeoutTests(unittest.TestCase):
    def test_explicit_timeout(self):
        self.assertEqual(_resolve_chat_timeout(12), 12)
        self.assertEqual(_resolve_chat_timeout(1.9), 1)

    def test_config_defaults(self):
        old_chat = getattr(config, "CHAT_TIMEOUT", 60)
        old_code = getattr(config, "CODE_CHAT_TIMEOUT", 60)
        old_mode = getattr(config, "MODE", "agent")
        try:
            config.CHAT_TIMEOUT = 45
            config.CODE_CHAT_TIMEOUT = 30
            config.MODE = "agent"
            self.assertEqual(_resolve_chat_timeout(None), 45)
            config.MODE = "code"
            self.assertEqual(_resolve_chat_timeout(None), 30)
        finally:
            config.CHAT_TIMEOUT = old_chat
            config.CODE_CHAT_TIMEOUT = old_code
            config.MODE = old_mode


class ChatCompletionTimeoutTests(unittest.TestCase):
    def test_hanging_urlopen_raises_timeout(self):
        """Künstlich hängender Call muss nach Wall-Clock mit TimeoutError enden."""
        provider = OpenRouterProvider(
            url="http://127.0.0.1:9",
            model="test/model",
            api_key="test-key",
            fallback_model=None,
        )

        def hang(*_a, **_k):
            time.sleep(30)
            raise AssertionError("hängender Call hätte abgebrochen werden müssen")

        t0 = time.monotonic()
        with mock.patch("urllib.request.urlopen", side_effect=hang):
            with self.assertRaises(TimeoutError) as ctx:
                provider._chat_completion(
                    [{"role": "user", "content": "ping"}],
                    temperature=0.0,
                    timeout=1,
                    model="test/model",
                )
        elapsed = time.monotonic() - t0
        self.assertIn("timeout", str(ctx.exception).lower())
        # Wall-Clock ~1s, großzügig aber deutlich unter dem Sleep(30)
        self.assertLess(elapsed, 5.0, f"Timeout zu langsam: {elapsed:.2f}s")
        self.assertGreaterEqual(elapsed, 0.5)


class ThreadingHealthIsolationTests(unittest.TestCase):
    """Simuliert den Server-Kern: threaded Handler, hängender /chat, /health ok."""

    def test_health_during_hanging_chat(self):
        hang_entered = threading.Event()
        release_hang = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_GET(self):
                if self.path.startswith("/health"):
                    body = b'{"status":"ok"}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_error(404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0) or 0)
                if length:
                    self.rfile.read(length)
                hang_entered.set()
                # Simuliert blockierenden OpenRouter-Call
                release_hang.wait(timeout=30)
                body = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            # Hängenden Chat im Hintergrund starten
            def post_chat():
                try:
                    req = urllib_request.Request(
                        f"http://127.0.0.1:{port}/chat",
                        data=b'{"message":"hang"}',
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    urllib_request.urlopen(req, timeout=15).read()
                except Exception:
                    pass

            chat_t = threading.Thread(target=post_chat, daemon=True)
            chat_t.start()
            self.assertTrue(hang_entered.wait(3), "hängender /chat startete nicht")

            # Während Hang: Health muss innerhalb kurzer Zeit antworten
            t0 = time.monotonic()
            with urllib_request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=2
            ) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            elapsed = time.monotonic() - t0
            self.assertEqual(resp.status, 200)
            self.assertEqual(data.get("status"), "ok")
            self.assertLess(elapsed, 1.5, f"Health zu langsam: {elapsed:.2f}s")
        finally:
            release_hang.set()
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
