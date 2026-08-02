# glyph-agent — persönlicher lokaler Obsidian-Assistent

Ein schlanker, **DSGVO-bewusster** Assistent, der mit deinem Obsidian-Vault arbeitet.
Standardmäßig **komplett lokal** über Ollama (Qwen). Optional kann der Agentenmodus ein
OpenRouter-Cloud-Modell zur Antwortformulierung nutzen (mit lokalem Fallback), und es gibt
einen davon getrennten reinen OpenRouter-Chat-Modus **ohne** Vault-/Tool-Zugriff.

## Zwei getrennte Betriebsarten

| MODE | Bedeutung | Standard |
|------|-----------|----------|
| `agent` | **Agentenmodus** — lokaler Agent greift auf Wiki/Tools zu | `agent/ollama` *(voll lokal)* |
| `openrouter-chat` | **Reine Chat-Oberfläche** — kein Wiki/Vault/Tools | keine Agentenrechte |

> **Wichtig:** `MODE=agent` bedeutet **NICHT** automatisch OpenRouter. Der tatsächliche
> Standard ist `MODE=agent` + `AGENT_PRIMARY_PROVIDER=ollama` → **komplett lokaler Betrieb**.
> OpenRouter wird erst aktiv, wenn `AGENT_PRIMARY_PROVIDER=openrouter` (siehe unten).

### Agentenmodus (`MODE=agent`)

Der lokale Agent kontrolliert Wiki-zugriff, Dateisuche, Tool-Aufrufe, Kontextauswahl,
Schreibbestätigung und den Fallback. Antwortkette, wenn OpenRouter als primärer Provider
gesetzt ist:

```text
1. bevorzugtes OpenRouter-Modell      (AGENT_OPENROUTER_MODEL)
2. kostenloses OpenRouter-Modell      (AGENT_OPENROUTER_FALLBACK_MODEL, z. B. ...:free)
3. lokales Qwen                       (AGENT_LOCAL_FALLBACK_PROVIDER)
```

Ist der Primär-Provider `ollama`, wird **keine** Cloud angefragt (lokaler Datenschutzmodus).

### Reiner OpenRouter-Chat (`MODE=openrouter-chat`)

Vollständig getrennt vom Agenten: **kein** Vault-Zugriff, **keine** lokalen Tools, **kein**
Wiki-Kontext, **kein** automatischer Wechsel zu Qwen. Bei OpenRouter-Ausfall nur eine
Fehlermeldung. Nur Chat (`OPENROUTER_MODEL` → optional `OPENROUTER_FALLBACK_MODEL`).

## Betriebszustände im Überblick

```text
MODE=agent + AGENT_PRIMARY_PROVIDER=ollama
→ Agent arbeitet vollständig lokal (Standard, DSGVO-sicher)

MODE=agent + AGENT_PRIMARY_PROVIDER=openrouter
→ bevorzugtes OpenRouter-Modell → kostenloses OpenRouter-Modell → lokales Qwen

MODE=openrouter-chat
→ reine OpenRouter-Chat-Oberfläche; kein lokaler Zugriff; kein Qwen-Fallback
```

**MODE vs. AGENT_PRIMARY_PROVIDER:** `MODE` wählt die Betriebsart (Agentenmodus vs.
Chat-Oberfläche). `AGENT_PRIMARY_PROVIDER` wählt *innerhalb* des Agentenmodus, ob lokal
(`ollama`) oder mit Cloud-Formulierung (`openrouter`) gearbeitet wird.

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
| `AGENT_PRIMARY_PROVIDER` | `ollama` | Innerhalb Agentenmodus: `ollama` (lokal) \| `openrouter` (Cloud) |
| `AGENT_OPENROUTER_MODEL` | `deepseek/deepseek-chat` | Bevorzugtes Cloud-Modell im Agentenmodus |
| `AGENT_OPENROUTER_FALLBACK_MODEL` | `inclusionai/ling-3.0-flash:free` | Kostenloses OpenRouter-Modell (Stufe 2) |
| `AGENT_LOCAL_FALLBACK_PROVIDER` | `ollama` | Lokales Qwen (Stufe 3, nur Agentenmodus) |
| `OPENROUTER_MODEL` | `deepseek/deepseek-chat` | Modell im `openrouter-chat`-Modus |
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
AGENT_OPENROUTER_MODEL=deepseek/deepseek-chat
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

## Geplante Ausbaustufen (erst nach persönlichem Bewähren)

1. **V1 (aktuell):** Vault lesen/suchen/zusammenfassen, Notizen erstellen,
   bearbeiten mit Diff + Backup. Web optional.
2. **V2:** Task-Extraktion (Fristen), Vorlagen ausfüllen, wiederverwendbare
   Workflows.
3. **V3 (Produkt, nur falls gewünscht):** Mac-mini-Portierung, konfigurierbarer
   Vault-Pfad, mehrere Vaults/Benutzer, Installer — erst DANN.

> „Persönliche Funktionalität vor Produktarchitektur."
