#!/usr/bin/env node
/**
 * glyph-agent-acp.mjs — ACP-Stdio-Adapter: Glyph (ACP-Client) <-> glyph-agent (lokal)
 *
 * Dünne Brücke: Glyph spricht ACP, glyph-agent liefert die Tool-Orchestrierung
 * (Vault, Obsidian, Recherche) über das lokale Modell. Dieser Adapter hat
 * KEINE Agentenlogik — er leitet an den glyph-agent-HTTP-Dienst (POST /chat)
 * durch und streamt die Antwort als Text-Chunks zurück an Glyph.
 *
 * Vorteil: Das Modell (Qwen heute, später MLX/anderes) und die Tool-Schicht
 * bleiben in glyph-agent gekapselt; hier wird NUR übersetzt (dünne Brücke).
 *
 * Protokoll: ACP v1 über NDJSON-Stdio (acp.ndJsonStream).
 * Copyright (c) 2026 Alexander Hubert · SPDX-License-Identifier: MIT
 */
import * as acp from "@agentclientprotocol/sdk";
import { Readable, Writable } from "node:stream";

// glyph-agent HTTP-Dienst (Standard wie in server.py)
const AGENT_URL = process.env.GLYPH_AGENT_URL || "http://127.0.0.1:18899";
const TIMEOUT_MS = Number(process.env.GLYPH_AGENT_TIMEOUT || 300000);
const PROTOCOL_VERSION = acp.PROTOCOL_VERSION;

// In-Memory Session-Speicher (Test/Zustand; ohne Langzeit-Persistenz)
const sessions = new Map();
let sessionCounter = 0;
const newSessionId = () => `glyph-agent-${++sessionCounter}`;

function blocksToText(contentBlocks) {
  if (!Array.isArray(contentBlocks)) return "";
  const parts = [];
  for (const block of contentBlocks) {
    if (block && block.type === "text" && typeof block.text === "string") {
      parts.push(block.text);
    }
  }
  return parts.join("\n").trim();
}

function streamChunks(text, client, sessionId, chunkSize = 400) {
  // Zerlegt die Antwort in Chunks und sendet sie als agent_message_chunk,
  // damit Glyph (wie bei Ollama-Stream) zeichenweise aufbauen kann.
  if (!text) return Promise.resolve();
  const chunks = [];
  for (let i = 0; i < text.length; i += chunkSize) {
    chunks.push(text.slice(i, i + chunkSize));
  }
  return Promise.all(
    chunks.map(async (c, idx) => {
      try {
        await client.notify(acp.methods.client.session.update, {
          sessionId,
          update: {
            sessionUpdate: "agent_message_chunk",
            content: { type: "text", text: c },
            complete: idx === chunks.length - 1,
          },
        });
      } catch (e) {
        // still
      }
    })
  );
}

const app = acp.agent({ name: "glyph-agent" });

app.onRequest(acp.methods.agent.initialize, async () => ({
  protocolVersion: PROTOCOL_VERSION,
  agentCapabilities: {
    loadSession: false,
    promptCapabilities: {},
    sessionCapabilities: {},
  },
  agentInfo: { name: "glyph-agent", version: "0.2.0" },
}));

app.onRequest(acp.methods.agent.authenticate, async () => ({}));
app.onRequest(acp.methods.agent.logout, async () => ({}));

app.onRequest(acp.methods.agent.session.new, async () => {
  const sessionId = newSessionId();
  sessions.set(sessionId, { messages: [] });
  return { sessionId };
});

app.onRequest(acp.methods.agent.session.list, async () => ({
  sessions: [...sessions.keys()].map((id) => ({
    id,
    path: null,
    title: null,
    updatedAt: Date.now(),
    additionalDirectories: [],
  })),
}));

app.onRequest(acp.methods.agent.session.close, async ({ params }) => {
  sessions.delete(params.sessionId);
  return {};
});

app.onRequest(acp.methods.agent.session.delete, async ({ params }) => {
  sessions.delete(params.sessionId);
  return {};
});

// --- session/prompt: dünne Brücke zu glyph-agent /chat ---
app.onRequest(acp.methods.agent.session.prompt, async (ctx) => {
  const { params, signal, client } = ctx;
  const sessionId = params.sessionId;
  const store = sessions.get(sessionId);
  if (!store) {
    const err = new Error(`Unbekannte Session: ${sessionId}`);
    err.code = -32602;
    throw err;
  }

  const userText = blocksToText(params.prompt);
  store.messages.push({ role: "user", content: userText });

  const abortController = new AbortController();
  const onAbort = () => abortController.abort();
  signal.addEventListener("abort", onAbort, { once: true });

  try {
    const resp = await fetch(`${AGENT_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: userText }),
      signal: abortController.signal,
    });
    if (!resp.ok) {
      throw new Error(`glyph-agent HTTP ${resp.status} — läuft der lokale Dienst? (server.py)`);
    }
    const data = await resp.json();
    const answer = data?.answer ?? "";

    store.messages.push({ role: "assistant", content: answer });

    // Antwort als Chunks nach Glyph streamen
    await streamChunks(answer, client, sessionId);

    // Abschluss als finales Ergebnis signalisieren
    try {
      await client.notify(acp.methods.client.session.update, {
        sessionId,
        update: {
          sessionUpdate: "agent_message_complete",
          message: { role: "assistant", content: [{ type: "text", text: answer }] },
        },
      });
    } catch (e) {
      // optional
    }

    return { stopReason: "end_turn" };
  } catch (err) {
    signal.removeEventListener("abort", onAbort);
    if (err.name === "AbortError") {
      return { stopReason: "stop" };
    }
    throw err;
  }
});

// --- session/cancel notification ---
app.onNotification(acp.methods.agent.session.cancel, async () => {
  // Abbruch wird über das AbortSignal des laufenden prompt gehandhabt.
  return;
});

// --- Stdio-Verbindung aufspannen ---
// process.stdout/stdin sind Node-Streams; ndJsonStream braucht WHATWG-Web-Streams.
const stream = acp.ndJsonStream(
  Writable.toWeb(process.stdout),
  Readable.toWeb(process.stdin),
);

const connection = app.connect(stream);

// Fehler am Ende nicht stumm verschlucken
connection.closed.catch(() => {}).finally(() => {
  process.exit(0);
});
