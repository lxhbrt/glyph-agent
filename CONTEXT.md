# glyph-agent

Lokale Engine hinter dem Glyph-Profil **glyph-agent**: Vault-Gedächtnis, Recherche-Tools und Cloud-Antwort. Eigenes Domänenvokabular — getrennt von Glyph-UI.

## Orient (für ^_Code / Agenten)

1. Diese Datei zuerst lesen — **nicht** blind ListDir/Grep über `core/`.
2. Aufgabe → **Node** → nur deren Quellen. MODE entscheidet den Pfad (`agent` vs `code`).
3. Neue Route/Tool/Registry → Map hier updaten; SoT-Pfade (`~/.glyph/*`) nicht im Code hardcoden ohne Registry.

## System map

| Node | Tut | Quellen | Hängt an / produziert |
|------|-----|---------|------------------------|
| **HTTP** | `/chat`, `/health`, vaults/workspaces/recurring CRUD | `server.py` | alle Loops |
| **Agent-Loop** | B+: VaultFind → Tools → Cloud-Denker | `core/tool_loop.py`, `core/agent.py` | retrieval, research, vault_tools |
| **Code-Loop** | ^_Code: Read/Write/Grep/Shell, Confirm/Elevated | `core/code_loop.py`, `core/code_tools.py` | `workspaces_registry` |
| **Tools-Registry** | Tool-Namen, Schemas, Dispatch | `core/tool_registry.py` | tool_loop / code_loop |
| **Bind-Store** | Persistenz + Kern-PATCH für Vaults+Workspaces | `core/bind_store.py` | vaults_registry, workspaces_registry |
| **Vaults** | `~/.glyph/vaults.json`, Pins, Privat-Block | `core/vaults_registry.py` | Index, VaultFind |
| **Workspaces** | `~/.glyph/workspaces.json` r/r+w/🔒 | `core/workspaces_registry.py` | code_tools Pfadchecks |
| **Retrieval** | Embeddings `bge-m3` + Keyword hybrid | `core/retrieval.py` | Ollama lokal |
| **Research** | Exa grob, TinyFish fein | `core/research.py`, `core/web.py` | tool_loop |
| **Recurring/Jobs** | Plan, Catch-up, HSEQ-Seeds | `core/recurring.py`, `jobs/`, `scripts/` | `jobs/recurring.json` |
| **LLM/Provider** | Direct Pro/Flash → OpenRouter 0731 | `core/llm.py`, `core/providers/` | config, Bindings |
| **Config** | Env, Models, Ports | `core/config.py`, `core/dotenv.py` | alles |
| **Verfassung** | B+-Regeln, Tabus | `CONSTITUTION.md` + **diese** CONTEXT | `~/.glyph/AGENTS.md`, MEMORY |

**Zwei Kontexte:** UI-Begriffe → `~/glyph-ui/CONTEXT.md`. Engine hier. Nicht vermischen.

**Crux:**  
- Write flüssig nur unter Workspace **`r+w`**; Elevated = `pending_confirmation` + `resume_token` (UI-Popup).  
- °_Agent default **kein Shell**. Shell nur `MODE=code`.  
- Embeddings **nur** lokal `bge-m3` — nie Cloud-Embedding.

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
_Avoid_: „3-Stufen-Fallback“ / lokaler Chat-Fallback (existiert nicht mehr; Direct Pro → OpenRouter Flash)

## Settled decisions (Direct-Hop 2026-08-12)

- °_Agent: Direct `deepseek-v4-pro` → OpenRouter `deepseek/deepseek-v4-flash-0731`.
- ^_Code: Direct `deepseek-v4-flash` → derselbe OpenRouter-0731.
- Key: `DIRECT_API_KEY` (Alias `DEEPSEEK_API_KEY`) + `DIRECT_API_URL` (Default `https://api.deepseek.com`). OpenAI-kompatibel, nicht DeepSeek-exklusiv.
- Thinking = API-Default. Chat `EXTERNAL_MAX_CHARS=8000`. Kein Tiny/Free.

## Settled decisions (grill 2026-08-05)

- UI-Sprache: **glyph-agent / Cloud-Antwort**; **OpenRouter** nur in Config/CONSTITUTION/Technik.
- Domain-Doku: eigenes `CONTEXT.md` hier (Engine); Glyph-UI hat eigenes CONTEXT — zwei Kontexte.
- Live-Test „grün“: Antwort + Steps **und** VaultFind erkennbar (Q8=B).
- Kein ADR nötig — CONTEXT reicht (Q9=C).

## Settled decisions (C′ 2026-08-07)

- **glyph-agent Default** bleibt **Vault-only** (kein Shell, kein allgemeines Repo-Schreiben).
- **`MODE=code`** (per Request `mode: "code"`): ^_Code-Pfad — Tools `ListDir` / `ReadFile` / `Grep` / `SearchReplace` / `WriteFile` / `RunCommand`, Denker `CODE_OPENROUTER_MODEL` (Default `deepseek/deepseek-v4-flash-0731`).
- **Workspaces-SoT:** `~/.glyph/workspaces.json` (Modes `r` / `rw` / `private`); Registry `core/workspaces_registry.py`. Fallback `CODE_WORKSPACE_ROOTS` nur wenn Store fehlt oder `CODE_WORKSPACES_USE_REGISTRY=false`; geladene leere/disabled Registry ist `[]`.
- Write/SearchReplace unter **`r+w` ohne Popup**. Whitelist-Shell unter `r+w` ohne Popup.
- **Elevated** braucht Glyph-Popup (`pending_confirmation` + `resume_token`): `git push|pull|fetch`, Compound, `npm run service:*`. Kein Session-Always für elevated.
- Fail nach Allow / unter r+w: **hard_error** + Banner (echter Grund). Hart-Deny: `rm`/`sudo`/… bleibt tot.
- Shell: Whitelist + Hard-Deny + Elevated-Klassifikation + Timeout; nur angebundene Roots.

## Settled decisions (Wiederkehrende To-dos 2026-08-08)

- **SoT:** `jobs/recurring.json` + `core/recurring.py`. UI: Glyph Kalender → Tab **Plan**.
- Schema: title, prompt, schedule daily|weekly (Europe/Berlin), paused, allow_write, last_*.
- Ausführen: Freitext → tool_loop; allow_write → Auto-Confirm nur HSEQ-Pfade. Globaler Job-Lock.
- Scheduler: `POST /recurring/run-due` via `jobs-catchup.sh` (15 Min). **Zusätzlich einmal beim Agent-Start** (Hintergrund-Thread, ~2s Delay; Catch-up-Plist kann vor dem Agent laufen). Keine Plist pro To-do.
- Migration: 3 HSEQ-Seeds (`td-eingang` 18:00, `td-handover` 18:30, `td-lernen` Fr 19:00).
- Fertig: last_status=ok → UI „Fertig“ klickbar löscht To-do. Events → Systemzeile in Glyph-UI.
- ACP-Plan-Leiste bleibt getrennt (Session).

## Settled decisions (Second-Brain Gaps 2026-08-09)

- Pro-Vault-Vertrag: `HSEQ Sync/AGENTS.md`; Wiki: erweiterte `memory-wiki/AGENTS.md` (Ingest ≥1 Synthese-Seite).
- Skills: `vault-ingest`, `merken` (+ bestehende hseq-*); IDs Alias `hseq-*` = recurring `td-*`.
- merken (2026-08-13): Schicht-Router — HSEQ-Themen / MEMORY §2 / Repo-CONTEXT / AGENTS nach Ja. Was nicht sofort ins Ziel darf → `~/.glyph/memory/pending-contract.md` (°_Agent darf genau diese eine Datei außerhalb der Vaults).
- Handover: Pflicht-**3-Zeilen-Briefing** (Neu / Offen / Konflikt-Stale); Eingang+Log = Beleg, nicht Offen.
- Index: `_is_blocked` + Hygiene blocken heikle Privat-/Behörden-Pfadmuster (nicht alle `unsafe-local-*`).
- Privat bleibt außerhalb `VAULT_PATHS` (Red Line).

## Settled decisions (Shared SoT alle Profile 2026-08-09)

- **Eine** Querschnitts-Wahrheit: `~/.glyph/AGENTS.md` — Grok, ^_Code, °_Agent.
- Skills gemeinsam: `~/.glyph/skills/` (Glyph-UI `skillRootsForProfile` für alle Profile).
- Grok: `~/.grok/rules/glyph-shared.md`. Agent/Code: Prompt-Injection der SoT-Datei.
- Nutzer muss Geklärtes nicht pro Profil neu erzählen.

## Settled decisions (zentrale Memory 2026-08-09)

- **Memory:** `~/.glyph/MEMORY.md` (kuratiert: Resümee + Lektionen aus Fehlern).
- Nicht unter OpenClaw; Stub + Backup unter `~/.openclaw/workspace/MEMORY.md*`.
- Tages-Archiv: `~/.glyph/memory/openclaw-dailies/` → alte OpenClaw-Dailies.
- Glyph übernimmt Operatives; OpenClaw Auslauf (Rest-Crons 03:00/06:00 bis Ersatz).

## Settled decisions (^_Code Workspaces Phase 1 — 2026-08-11)

- **Problem:** Allow + Fail — Code fragt freigeben, setzt aber nichts um.
- **Capability first** (Phase 1), Kabelsalat-UI Workspaces = Phase 2.
- SoT `~/.glyph/workspaces.json`; nur Profil **`^_Code`** (Grok unberührt).
- Defaults: glyph-ui + glyph-agent = `r+w`; openclaw-workspace = `r`.
- Write flüssig unter r+w; Popup nur elevated; hart-deny bleibt; Fail = hard stop + Banner.

## Settled decisions (^_Code Loop — Grill 2026-08-13)

- **Job:** Mehrdatei E2E (lesen → schreiben → Whitelist-Test → kurz sagen).
- **Verlauf:** echte `messages[]` an Direct/OpenRouter. Budget `CODE_MESSAGE_CHARS` (64k). Älteste Turns weg; **erstes User + letztes Tool-Ergebnis bleiben**. Kein Flatten, das neue Ergebnisse abschneidet.
- **Orient:** alle **r+w**-`CONTEXT.md` (Abschnitte Orient + System map) im System-Prompt. `r`-Roots eine Zeile. Kein Blind-Grep.
- **Denker:** Flash bleibt; kein Provider-Wechsel ohne neuen Beleg.
- **Runden:** `CODE_MAX_ROUNDS=32`. Timeout 180s.
- **SearchReplace 0×/N×:** zurück in die Loop. Hart tot nur Deny / 🔒 / Nutzer-Ablehnung / Shell-Timeout / Test-Fail.
- **Grep/ListDir 3× gleich:** nicht ausführen — „Map nutzen oder antworten“.
- **Nach Write/Replace:** `npm test` oder `pytest` im angebundenen Root (Whitelist, kein Popup). `npm run service:*` bleibt Elevated.

## Settled decisions (^_Code Workspaces Phase 2 — 2026-08-11)

- Kabelsalat-UI analog Vaults: Buch → Tab **Workspaces**, Hub `^_Code`.
- API: `GET|POST /workspaces`, `PATCH|DELETE /workspaces/<id>` → Registry CRUD.
- UI-Proxy: glyph-ui `/api/workspaces` → Agent.
- Modes: `r` · `rw` · `private` (UI: gesperrt). Keine Pins, kein Obsidian-URI.
- Anbinden: existierendes Verzeichnis (Pfad oder Name unter `$HOME`).

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
