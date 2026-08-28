# 0002 · Vault wächst, Glyph löscht nicht

°_Agent darf im Chat Themen- und Wiki-Notizen anlegen und ergänzen, ohne Freigabe-Dialog. Es gibt kein Delete. Leeren und Umschreiben von Eingang/Sources sind tot. Die Wissensbasis soll wachsen; der Schaden ist dummes Entfernen, nicht dummes Anlegen.

## Considered

- Freigabe analog ^_Code — abgelehnt: ein Nutzer, Wachstum soll nicht am Popup hängen.
- Auto-Write auf jedes `r+w`-Vault — abgelehnt: Home-Root und Hauptarchiv wären offen.
- Nur CreateNote, kein ApplyEdit — abgelehnt: Hubs (PSA → Nomex) müssen ergänzbar bleiben; Backup fängt Fehl-Edits.

## Consequences

- Chat-Confirm: `core/vault_write_policy.py` (`Themen/`, Wiki-Schichten, pending-contract).
- `apply_edit`/`create_note` weisen leeren Inhalt ab.
- Jobs behalten ihre HSEQ-Präfixe (inkl. Vorlagen/Daily); sie erben den Leer-Guard.
- Web-Fläche dieselben Pfade — Passwort-Tor bleibt die Tür.
- Ausnahme 2026-08-28: Script-Job `td-wiki-hygiene` darf **nur** in `memory-wiki` doppelt tote Dateien nach `_hygiene-trash/YYYY-MM-DD/` schieben (30 Tage). Chat bleibt ohne Delete. HSEQ/Privat/Hauptarchiv: nicht.
