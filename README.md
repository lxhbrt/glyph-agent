# glyph-agent — persönlicher lokaler Obsidian-Assistent (B+)

Schlanker Agent: **lokales Vault-Gedächtnis** + **Cloud-Denker** (OpenRouter).
Spielregeln: [`CONSTITUTION.md`](./CONSTITUTION.md).

## Architektur B+ (aktuell)

```text
Nutzerfrage
  → VaultFind (Hybrid: 0.7 Embedding bge-m3 + 0.3 Keyword)   [lokal]
  → Web bei Bedarf: Exa = grob · TinyFish = fein              [API]
  → OpenRouter openai/gpt-5.6-luna formuliert                [Cloud]
  → Antwort + Trace/Steps
```

**Qwen ist kein Chat-Modell mehr.** Ollama läuft nur noch für **Embeddings** (`bge-m3`).

## Zwei Betriebsarten

| MODE | Bedeutung | Standard |
|------|-----------|----------|
| `agent` | VaultFind + Tools + Cloud-Antwort | `agent` + `openrouter` |
| `openrouter-chat` | Reiner Chat — kein Wiki/Vault/Tools | — |

### Provider (ehrlich)

| `AGENT_PRIMARY_PROVIDER` | Verhalten |
|--------------------------|-----------|
| **`openrouter`** (B+-Default) | Nur Cloud-Denker. **Kein** automatischer Qwen-Fallback. |
| `fallback` | **Nur wenn explizit gesetzt:** OpenRouter → `:free` → optional lokal. |
| `ollama` | Veraltet für Chat (nicht empfohlen). |

> Frühere Doku behauptete „immer 3 Stufen bei openrouter“ — das war **falsch**.
> Die 3-Stufen-Kette existiert nur bei `PROVIDER=fallback`.

## Architektur-Prinzip

```
Glyph (Browser) → glyph-agent HTTP (server.py:18899) → Tool-Loop → Qwen/OpenRouter
                                                              ↓
                                                  Vault (Obsidian) · Web (Exa/TinyFish)
```

- **Keine große Agenten-Bibliothek**, keine MCP.
- Werkzeuge = einfache Python-Funktionen (`core/vault_tools.py`) mit Whitelist + Bestätigung.
- Nur Python-stdlib + lokales Ollama; Web-Recherche optional Exa/TinyFish.

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
9. **Datenschutz-Schranke:** `EXTERNAL_MAX_CHARS` (Default 4000) kürzt Kontext vor Cloud-Übergabe;
   lokales Ollama bleibt ungekürzt.
10. **Modus-Trennung:** `openrouter-chat` hat KEINE Tools/Vault/Dateien — isolierte Oberfläche.

## Nutzung

### Lokaler HTTP-Dienst (Hauptweg über Glyph)

```bash
python3 server.py          # POST /chat, GET /health auf 127.0.0.1:18899
curl http://127.0.0.1:18899/health
curl -X POST http://127.0.0.1:18899/chat -H 'Content-Type: application/json' \
     -d '{"message": "Was steht im Vault zu Brandschutz?"}'
```

Antwort enthält `used_provider` / `used_model` (welches Modell geantwortet hat — wichtig
bei `fallback`). Ohne `confirm`-Liste werden Schreib-Tools (ApplyEdit/CreateNote) abgelehnt.

### Kommandozeile (CLI)

```bash
# Suchen (liest Treffer + Modell ordnet ein)
python3 -m scripts.cli search "Altöl"

# Notiz lesen
python3 -m scripts.cli read "Themen/PSA.md"

# Notiz zusammenfassen / analysieren (Qwen, nur lesend)
python3 -m scripts.cli summarize "Themen/PSA.md"
python3 -m scripts.cli summarize "Themen/PSA.md" "mit Fokus auf Fristen"

# Neue Notiz erstellen (überschreibt nie etwas)
python3 -m scripts.cli create "test/Neue Notiz.md" "Abfallregister vorhanden"

# Änderung vorschlagen → Diff ansehen → bestätigen → Backup+Schreiben
python3 -m scripts.cli propose "Themen/PSA.md" "Füge Abschnitt Prüfintervalle ein"

# Revisions-Backups ansehen
python3 -m scripts.cli backups

# Web-Recherche (kontrolliert; Exa-API, keine privaten Inhalte senden)
python3 -m scripts.cli web "TRGS 510 Aktuelle Anforderungen"
```

### Selbsttest

```bash
python3 tests/test_providers.py   # Provider-Routen + Fallback-Fehlerweg (9 Checks)
```

## Konfiguration

Alle Werte in `core/config.py` bzw. per Umgebungsvariable/`.env` (siehe auch `.env.example`).

**Primär-Vault:** `VAULT_PATH` → z. B. `/Users/<du>/ObsidianVaults/HSEQ Sync`.

**Betriebsart:**

| Variable | Default | Bedeutung |
|----------|---------|-----------|
| `MODE` | `agent` | `agent` (Agentenmodus) \| `openrouter-chat` (reiner Chat) |
| `AGENT_PRIMARY_PROVIDER` | `openrouter` | B+: `openrouter` \| explizit `fallback` (3 Stufen) \| `ollama` (veraltet) |
| `AGENT_OPENROUTER_MODEL` | `openai/gpt-5.6-luna` | Cloud-Denker |
| `AGENT_OPENROUTER_FALLBACK_MODEL` | `inclusionai/ling-3.0-flash:free` | Nur bei `PROVIDER=fallback` |
| `AGENT_LOCAL_FALLBACK_PROVIDER` | `ollama` | Nur bei `PROVIDER=fallback` (nicht B+) |
| `OPENROUTER_MODEL` | `openai/gpt-5.6-luna` | Modell im `openrouter-chat`-Modus |
| `OPENROUTER_FALLBACK_MODEL` | `inclusionai/ling-3.0-flash:free` | Kostenloses Modell im `openrouter-chat` |
| `OPENROUTER_ALLOW_TOOLS` | `false` | Tools im Chat-Modus (nicht empfohlen) |
| `OPENROUTER_ALLOW_VAULT` | `false` | Vault im Chat-Modus (nicht empfohlen) |
| `EXTERNAL_MAX_CHARS` | `4000` | Datenschutz-Schranke (Kürzung vor Cloud-Übergabe) |
| `BLOCKED_DIRS` | s. o. | Geschützte Vault-Ordner (kommagetrennt) |
| `EXA_API_KEY` / `TINYFISH_API_KEY` | — | Web-Recherche (nur `web`-Tool) |
| `OPENROUTER_API_KEY` | — | Nur für OpenRouter-Modi (nicht im lokalen Standard) |

**Beispiel — Agentenmodus mit OpenRouter-Primär + lokalem Fallback:**

```env
MODE=agent
AGENT_PRIMARY_PROVIDER=openrouter
AGENT_OPENROUTER_MODEL=openai/gpt-5.6-luna
AGENT_OPENROUTER_FALLBACK_MODEL=inclusionai/ling-3.0-flash:free
AGENT_LOCAL_FALLBACK_PROVIDER=ollama
OPENROUTER_API_KEY=sk-or-…
```

## Projektstruktur

```
glyph-agent/
├── server.py           # lokaler HTTP-Dienst (POST /chat, GET /health, Modus-Trennung)
├── core/
│   ├── config.py       # zentrale Konfiguration (Vault-Pfad, MODE, Provider, Blocklist)
│   ├── log.py          # Aktions-Protokoll (JSON-Lines)
│   ├── llm.py          # Provider-Brücke (nur hier Modellaufrufe)
│   ├── tool_loop.py    # kontrollierter Agenten-Loop (Runden-Limit, Halluzinations-Fix)
│   ├── tool_registry.py# Whitelist-Tools + write-Flag/Bestätigung (VaultSearch, WebSearch, …)
│   ├── vault_tools.py  # Tools: search/read/create/propose/apply + Pfad-/Ordner-Sicherheit
│   ├── agent.py        # Orchestrator (System-Prompt, Workflows)
│   ├── web.py          # Exa + TinyFish (Suche/Extraktion), kontrolliert
│   └── providers/      # austauschbare Modell-Adapter
│       ├── ollama.py   #   lokales Qwen
│       ├── openrouter.py # Cloud-Modell (auditiert, Kürzung)
│       ├── fallback.py #   Agentenmodus-Kette: bevorzugt → kostenlos → lokal
│       └── factory.py  #   wählt Provider
├── scripts/
│   └── cli.py          # lokale Oberfläche (Kommandozeile)
├── tests/
│   └── test_providers.py # Selbsttest Provider/Fallback (9 Checks)
├── vault/backups/      # Revisions-Backups (gitignored)
└── logs/               # Aktions-Protokoll (gitignored)
```

## Tools (B+)

| Tool | Rolle |
|------|--------|
| **VaultFind** | Ein Finde-Werkzeug (Hybrid Embedding+Keyword). Aliase: VaultRecall, VaultSearch |
| ReadNote / Summarize / CreateNote / ProposeEdit / ApplyEdit | Vault lesen/schreiben |
| WebSearch (Exa) | grobe Websuche |
| ExtractUrl / FetchUrl (TinyFish) | feine Zielseiten |
| ObsidianOpen | optional kepano-CLI, pfadgebunden |

Index-Hygiene (Bericht, kein Löschen): `python3 scripts/index_hygiene.py`

## Geplante Ausbaustufen

1. **V1 (aktuell):** B+ Pipeline, Hybrid-Find, Trace/Steps, Diff+Backup.
2. **V2:** PDF-Inhalte, Task-Extraktion, Workflows.
3. **V3 (nur falls gewünscht):** Produkt/Installer.

> „Persönliche Funktionalität vor Produktarchitektur."
