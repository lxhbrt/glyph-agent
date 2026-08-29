# Task-scoped Freigaben statt r+w-Auto-Write

`r+w` erlaubte WriteFile/SearchReplace und Whitelist-Shell ohne Popup. Eine Anbindung wurde zur Dauerberechtigung: späterer Auftrag, anderer Pfad, `npm install` oder `git commit` liefen still, sobald der Workspace beschreibbar war.

Entscheidung: Recht und Freigabe trennen. `r+w` heißt nur, dass Apply möglich ist. Jede Apply-Aktion braucht einen Grant (Einmal / Auftrag / Task) mit Root, Pfadpräfixen, Aktionsklassen und Ablauf. Die Regex-Whitelist bleibt hartes Minimum, nicht die Erlaubnis. Chat-Session ist kein Scope. Task nur explizit schließen; außerhalb des Scopes greift kein Grant. Einmal gilt für den ganzen Änderungssatz. Kein `w` im Kabelsalat.

## Considered Options

- **Session-Always (Codex)** — Thread/Turn-Bindung ist näher, aber Session überlebt die Aufgabe. Für Glyph zu weit.
- **Nur elevated popupt, Rest auto** — Status quo. Schnell, unsichtbar dauerhaft. Abgelehnt.
- **Immer-erlauben** — falscher Default für Write/Shell.

## Consequences

- `permission_decision` liefert `requires_grant` statt `allow` für Writes unter `r+w`.
- Grant-Store in `code_loop` neben `resume_token`; Scope-Check vor jeder Tool-Aktion.
- Änderungssatz vor Disk-Write; Tests nach Apply; kein Auto-Commit.
- `git commit` fällt aus dem stillen Whitelist-Allow.
- Shared SoT `~/.glyph/AGENTS.md` (Stand 2026-08-22): r+w = Capability, nicht Auto-Write.
