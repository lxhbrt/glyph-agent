# glyph-agent — persönlicher lokaler Obsidian-Assistent (B+)

Schlanker Agent: **lokales Vault-Gedächtnis** + **Cloud-Denker** (OpenRouter).
Spielregeln: [`CONSTITUTION.md`](./CONSTITUTION.md).

## Architektur B+ (aktuell)

```text
Nutzerfrage
  → VaultFind (Hybrid: 0.7 Embedding bge-m3 + 0.3 Keyword)   [lokal]
  → Web bei Bedarf: Exa = grob · TinyFish = fein              [API]
  → OpenRouter openai/gpt-5.6-luna formuliert                [Cloud]
       → bei Ausfall: inclusionai/ling-3.0-flash:free
  → Antwort + Trace/Steps
```

Ollama läuft **nur** für **Embeddings** (`bge-m3`) — **kein** Chat.

## Zwei Betriebsarten

| MODE | Bedeutung | Standard |
|------|-----------|----------|
| `agent` | VaultFind + Tools + Cloud-Antwort | `agent` + `openrouter` |
| `openrouter-chat` | Reiner Chat — kein Wiki/Vault/Tools | — |

### Provider

| `AGENT_PRIMARY_PROVIDER` | Verhalten |
|--------------------------|-----------|
| **`openrouter`** (B+-Default) | Luna → free bei Ausfall. Kein lokaler Chat. |
| `fallback` | Alias derselben 2-Stufen-Cloud-Kette. |

## Architektur-Prinzip

```
Glyph (Browser) → glyph-agent HTTP (server.py:18899) → Tool-Loop → OpenRouter (Luna → free)
                                                              ↓
                                                  Vault (Obsidian) · Web (Exa/TinyFish)
```

- **Keine große Agenten-Bibliothek**, keine MCP.
- Werkzeuge = einfache Python-Funktionen (`core/vault_tools.py`) mit Whitelist + Bestätigung.
- Nur Python-stdlib + Ollama für Embeddings; Web-Recherche optional Exa/TinyFish.

## Sicherheitsmaßnahmen

1. **Pfad-Sicherheit:** Zugriff nur innerhalb des Vaults (Block gegen `../`-Escape/Symlinks).
2. **Kein Löschen/Umbenennen** — nur Lesen, Erstellen, Bearbeiten.
3. **Änderungsvorschau (Diff):** Vor jedem Schreiben zeigt der Agent einen Unified-Diff;
   du bestätigst, sonst wird nichts geschrieben.
4. **Backup + Revisionsnummer:** Vor jedem Schreiben wird der alte Inhalt in `vault/backups/`
   gesichert (R1, R2, …) — atomar via Temp+rename.
5. **Zentrale Schreibfunktion:** Schreiben läuft NUR über `apply_edit` — nie direkt anderswo.
6. **Prompt-Injection-Schutz:** Vault-Dateien sind DATEN, keine Anweisungen.
7. **Geschützte Ordner:** `BLOCKED_DIRS` (Default: private, privat, secrets, health, geheim,
   persönlich, personenbezogen) werden von Suche/Lesen/Editieren ausgeschlossen (env-überschreibbar).
8. **Cloud-Audit:** Jede Übertragung an OpenRouter wird in `logs/actions.jsonl` protokolliert
   (provider, model, Zeichen, Zeit). Kein Senden ohne `OPENROUTER_API_KEY`.
9. **Datenschutz-Schranke:** `EXTERNAL_MAX_CHARS` (Default 4000) kürzt Kontext vor Cloud-Übergabe.
10. **Modus-Trennung:** `openrouter-chat` hat KEINE Tools/Vault/Dateien — isolierte Oberfläche.

## Nutzung

### Lokaler HTTP-Dienst (Hauptweg über Glyph)

```bash
python3 server.py          # POST /chat, GET /health auf 127.0.0.1:18899
curl http://127.0.0.1:18899/health
curl -X POST http://127.0.0.1:18899/chat -H 'Content-Type: application/json' \
     -d '{"message": "Was steht im Vault zu Brandschutz?"}'
```

Antwort enthält `used_provider` / `used_model` (welches Modell geantwortet hat —
Luna oder Free-Fallback). Ohne `confirm`-Liste werden Schreib-Tools abgelehnt.

### Kommandozeile (CLI)

```bash
python3 -m scripts.cli search "Altöl"
python3 -m scripts.cli read "Themen/PSA.md"
python3 -m scripts.cli summarize "Themen/PSA.md"
python3 -m scripts.cli summarize "Themen/PSA.md" "mit Fokus auf Fristen"
python3 -m scripts.cli create "test/Neue Notiz.md" "Abfallregister vorhanden"
python3 -m scripts.cli propose "Themen/PSA.md" "Füge Abschnitt Prüfintervalle ein"
python3 -m scripts.cli backups
python3 -m scripts.cli web "TRGS 510 Aktuelle Anforderungen"
```

### Selbsttest

```bash
python3 tests/test_providers.py   # Provider-Routen + Free-Fallback-Pfad
```

## Konfiguration

Alle Werte in `core/config.py` bzw. per Umgebungsvariable/`.env`.

**Primär-Vault:** `VAULT_PATH` → z. B. `/Users/<du>/ObsidianVaults/HSEQ Sync`.

**Betriebsart:**

| Variable | Default | Bedeutung |
|----------|---------|-----------|
| `MODE` | `agent` | `agent` \| `openrouter-chat` |
| `AGENT_PRIMARY_PROVIDER` | `openrouter` | `openrouter` \| `fallback` (Alias) |
| `AGENT_OPENROUTER_MODEL` | `openai/gpt-5.6-luna` | Primär-Cloud-Denker |
| `AGENT_OPENROUTER_FALLBACK_MODEL` | `inclusionai/ling-3.0-flash:free` | Free bei Ausfall |
| `OPENROUTER_MODEL` | `openai/gpt-5.6-luna` | Modell im `openrouter-chat`-Modus |
| `OPENROUTER_FALLBACK_MODEL` | `inclusionai/ling-3.0-flash:free` | Free im Chat-Modus |
| `EXTERNAL_MAX_CHARS` | `4000` | Kürzung vor Cloud-Übergabe |
| `OPENROUTER_API_KEY` | — | Pflicht für Chat |

**Beispiel:**

```env
MODE=agent
AGENT_PRIMARY_PROVIDER=openrouter
AGENT_OPENROUTER_MODEL=openai/gpt-5.6-luna
AGENT_OPENROUTER_FALLBACK_MODEL=inclusionai/ling-3.0-flash:free
OPENROUTER_API_KEY=sk-or-…
```

## Projektstruktur

```
glyph-agent/
├── server.py           # lokaler HTTP-Dienst (POST /chat, GET /health)
├── core/
│   ├── config.py       # zentrale Konfiguration
│   ├── llm.py          # Provider-Brücke
│   ├── tool_loop.py    # Agenten-Loop
│   ├── tool_registry.py
│   ├── vault_tools.py
│   ├── agent.py
│   ├── web.py
│   └── providers/
│       ├── openrouter.py # Luna → free
│       ├── fallback.py   # Alias derselben Kette
│       └── factory.py
├── scripts/cli.py
├── tests/
├── vault/backups/
└── logs/
```

## Tools (B+)

| Tool | Rolle |
|------|--------|
| **VaultFind** | Hybrid Embedding+Keyword. Aliase: VaultRecall, VaultSearch |
| ReadNote / Summarize / CreateNote / ProposeEdit / ApplyEdit | Vault lesen/schreiben |
| WebSearch (Exa) | grobe Websuche |
| ExtractUrl / FetchUrl (TinyFish) | feine Zielseiten |
| ObsidianOpen | optional kepano-CLI, pfadgebunden |

Index-Hygiene: `python3 scripts/index_hygiene.py`

> „Persönliche Funktionalität vor Produktarchitektur."
