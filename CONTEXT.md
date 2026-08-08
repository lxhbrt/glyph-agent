# glyph-agent

Lokale Engine hinter dem Glyph-Profil **glyph-agent**: Vault-Gedächtnis, Recherche-Tools und Cloud-Antwort. Eigenes Domänenvokabular — getrennt von Glyph-UI.

## Language

**Nutzerantworten:** stop-slop (immer) — Kern zuerst, kein AI-Slop, keine erfundenen Normen.

**Cloud-Antwort**:
Die vom Cloud-Denker formulierte Nutzerantwort im B+-Pfad (nach VaultFind/Web/Tools). In UI und Nutzer-Doku so nennen.
_Avoid_: OpenRouter-Antwort, OpenRouter-Chat (als Nutzerbegriff)

**Cloud-Denker**:
Die Rolle des LLM, das die Antwort formuliert. Technik/Config darf den Provider nennen; Nutzer-UI nicht.
_Avoid_: OpenRouter als Synonym für diese Rolle in UI-Texten

**VaultFind**:
Ein nach außen sichtbares Finde-Werkzeug; intern hybrid Embedding + Keyword über erlaubte Vaults.
_Avoid_: VaultRecall, VaultSearch (Aliase, kein neuer Begriff)

**OpenRouter (Technik)**:
Config- und Provider-Name der Cloud-API (`AGENT_PRIMARY_PROVIDER`, CONSTITUTION, Logs). **Kein** Glyph-UI-Profil, **keine** Nutzer-Sprache in der UI.
_Avoid_: OpenRouter-Profil (entfernt)

**B+**:
Aktuelle Architektur: lokal Gedächtnis/Suche, Web nur bei Bedarf, Cloud-Denker formuliert, Antwort + Trace.
_Avoid_: „3-Stufen-Fallback“ / lokaler Chat-Fallback (existiert nicht mehr; nur Luna → free)

## Settled decisions (grill 2026-08-05)

- UI-Sprache: **glyph-agent / Cloud-Antwort**; **OpenRouter** nur in Config/CONSTITUTION/Technik.
- Domain-Doku: eigenes `CONTEXT.md` hier (Engine); Glyph-UI hat eigenes CONTEXT — zwei Kontexte.
- Live-Test „grün“: Antwort + Steps **und** VaultFind erkennbar (Q8=B).
- Kein ADR nötig — CONTEXT reicht (Q9=C).

## Settled decisions (C′ 2026-08-07)

- **glyph-agent Default** bleibt **Vault-only** (kein Shell, kein allgemeines Repo-Schreiben).
- **`MODE=code`** (per Request `mode: "code"`): ^_Code-Pfad — Tools `ListDir` / `ReadFile` / `Grep` / `SearchReplace` / `WriteFile` / `RunCommand`, Denker `CODE_OPENROUTER_MODEL` (Default `deepseek/deepseek-v4-flash-0731`).
- Write/Shell brauchen **Glyph-Genehmigung** (`pending_confirmation` + `resume_token`); nie auto-approve.
- Shell: Whitelist + Deny-Liste + Timeout + nur `CODE_WORKSPACE_ROOTS` (Default: glyph-ui, glyph-agent, `~/.openclaw/workspace`; optional `~/grok-chat-ui` wenn vorhanden; nur existierende Dirs).

## Settled decisions (Vault-Inventar 2026-08-08)

- **ListVaultDir** (Agent-Modus): Ordner im Vault listen (read-only). Für „was liegt im Eingang/Fertig?“ — Precheck bei Inventar-Fragen.
- **VaultFind** bleibt Inhaltssuche (Hybrid Embedding+Keyword); listet keine Ordner.
- **search_vault**: Token-Suche + Dateiname/Pfad (nicht nur Fullstring im Body). Datum nur im Namen zählt.
- Inventar-Fragen mit Jahreszahlen im Namen lösen **kein** Web-Precheck aus (domain-lokal).
- **Ranking:** Primär-Vault (`VAULT_PATHS[0]`, HSEQ Sync) und `00 Arbeitsfluss/Eingang|Fertig` vor OpenClaw-Wiki-`sources/` / `unsafe-local-*`-Hash-Slugs. Body-Treffer-Cap, damit lange Archiv-Kopien Datums-Queries nicht dominieren. Nutzer trifft gültige Live-Dateien, nicht alte Source-Nummern.

## Settled decisions (OpenClaw-Tools 2026-08-07)

- **°_Agent**: Wiki-Aliase `WikiSearch`→VaultFind, `WikiGet`→ReadNote, `WikiApply`→ApplyEdit; `WikiStatus` liest agent-digest (read-only).
- `BrowseUrl` = TinyFish Extract mit Summary-Goal; `ReadPdf` via pdftotext (Vault only); Mail via himalaya; `MessageSend` via openclaw (write+confirm).
- Kein Shell im Agent-Modus. Externe CLIs graceful degrade.
