# glyph-agent

Lokale Engine hinter dem Glyph-Profil **glyph-agent**: Vault-Gedächtnis, Recherche-Tools und Cloud-Antwort. Eigenes Domänenvokabular — getrennt von Glyph-UI.

## Language

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
