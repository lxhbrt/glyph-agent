# glyph-agent — persönlicher lokaler Obsidian-Assistent

Ein schlanker, **komplett lokaler** Assistent, der mit deinem Obsidian-Vault
arbeitet. Läuft über **Ollama** (lokales Qwen-Modell) — **ohne OpenClaw, ohne
Cloud-API für die Vault-Verarbeitung (DSGVO-sicher)**.

## Prinzip (persönlicher Sandkasten, nicht Verkaufsprodukt)

```
Lokale Oberfläche (CLI)
        ↓
Persönlicher Agent (core/agent.py)
        ↓
Lokales Qwen-Modell (Ollama)
        ↓
Dein Obsidian-Vault  (fester Pfad, siehe core/config.py)
```

- **Keine große Agenten-Bibliothek**, keine MCP, keine OpenClaw-Brücke.
- Werkzeuge = einfache Python-Funktionen (`core/vault_tools.py`).
- Nur Python-stdlib + lokales Ollama (für Web-Recherche optional Exa-API).
- Lauffähig später auch auf dem Mac mini (Portierung, wenn persönlich bewährt).

## Sicherheitsmaßnahmen (in dieser Phase bewusst beibehalten)

1. **Pfad-Sicherheit:** Zugriff nur innerhalb des Vaults (Block gegen `../`).
2. **Kein Löschen/Umbenennen** — nur Lesen, Erstellen, Bearbeiten.
3. **Änderungsvorschau (Diff):** Vor jedem Schreiben zeigt der Agent einen
   Unified-Diff; du bestätigst, sonst wird nichts geschrieben.
4. **Backup + Revisionsnummer:** Vor jedem Schreiben wird der alte Inhalt in
   `vault/backups/` gesichert (R1, R2, …) — atomar via Temp+rename.
5. **Zentrale Schreibfunktion:** Schreiben läuft NUR über `apply_edit`
   (Backup + atomar) — nie direkt irgendwo anders.
6. **Prompt-Injection-Schutz:** Vault-Dateien sind DATEN, keine Anweisungen.
   Der System-Prompt verbietet dem Modell, Inhalte zu befolgen.

## Nutzung (Kommandozeile)

Aus dem Projektordner:

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

## Konfiguration

- **Vault-Pfad:** `core/config.py` → `VAULT_PATH` (zentral, ein Ort).
- **Modell:** `core/config.py` → `OLLAMA_MODEL` (Default `qwen-solid`).
- **Web-Key:** Umgebungsvariable `EXA_API_KEY` (nur für `web`-Befehl).

## Projektstruktur

```
glyph-agent/
├── core/
│   ├── config.py        # zentrale Konfiguration (Vault-Pfad, Modell)
│   ├── log.py           # Aktions-Protokoll (JSON-Lines)
│   ├── llm.py           # Ollama-Schnittstelle (nur hier Modellaufrufe)
│   ├── vault_tools.py   # Tools: search/read/create/propose/apply (+Sicherheit)
│   ├── agent.py         # Orchestrator (System-Prompt, Workflows)
│   └── web.py           # kontrollierte Exa-Web-Recherche (optional)
├── scripts/
│   └── cli.py           # lokale Oberfläche
├── vault/backups/       # Revisions-Backups (gitignored)
└── logs/                # Aktions-Protokoll (gitignored)
```

## Geplante Ausbaustufen (erst nach persönlichem Bewähren)

1. **V1 (aktuell):** Vault lesen/suchen/zusammenfassen, Notizen erstellen,
   bearbeiten mit Diff + Backup. Web optional.
2. **V2:** Task-Extraktion (Fristen), Vorlagen ausfüllen, wiederverwendbare
   Workflows.
3. **V3 (Produkt, nur falls gewünscht):** Mac-mini-Portierung, konfigurierbarer
   Vault-Pfad, mehrere Vaults/Benutzer, Installer — erst DANN.

> „Persönliche Funktionalität vor Produktarchitektur."
