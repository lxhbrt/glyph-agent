# -*- coding: utf-8 -*-
"""
Konfiguration des persönlichen lokalen Assistenten (glyph-agent).

Diese Datei ist der EINZIGE Ort, an dem der Vault-Pfad zentral gesetzt wird.
Nicht in anderen Dateien hart verdrahten — siehe Architektur-Regel.
"""
import os

# --- Zentrale Pfad-Konfiguration (fest, persönlicher Sandkasten) ---
# Mehrere Obsidian-Vaults, mit denen der Assistent arbeitet (Recherche + Wiki-Anlage).
# Reihenfolge = Priorität für Pfad-Auflösung (erster Eintrag ist der 'Haupt'-Vault).
# Rechte (per Konvention):
#   - HSEQ Sync            : Lesen + Schreiben (Audits, Maßnahmenpläne)
#   - ASI, BS. UWS, QM, EM : Lesen (Facharchiv)
#   - OpenClaw memory-wiki : Lesen + Schreiben (Wiki selbst anlegen/pflegen)
#   - Peniel               : Lesen (Projekte)
# AUSGESCHLOSSEN (Red Line, nie automatisch): Privat, _RECOVERY, .obsidian, backups.
VAULT_PATHS = [
    "/Users/lxndrhbrt/ObsidianVaults/HSEQ Sync",
    "/Users/lxndrhbrt/ObsidianVaults/ASI, BS. UWS, QM, EM",
    "/Users/lxndrhbrt/ObsidianVaults/OpenClaw memory-wiki",
    "/Users/lxndrhbrt/ObsidianVaults/Peniel",
]

# Kompatibilitäts-Alias: erster Eintrag ist der primäre Vault (bisherige API nutzt VAULT_PATH).
VAULT_PATH = VAULT_PATHS[0]

# Backup-Verzeichnis für Revisionen (vor jeder Schreib-Änderung).
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vault", "backups")

# Protokoll-/Log-Datei (JSON-Lines) für alle Aktionen.
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", "actions.jsonl")

# --- Modell-Runtime (B+, Stand 2026-08-05) ---
# Betriebsart:
#   "agent"          : VaultFind + optional Web, Antwort durch Cloud-Denker (OpenRouter).
#   "openrouter-chat": reine Chat-Oberfläche OHNE Wiki/Tools.
# Siehe CONSTITUTION.md — Qwen ist KEIN Chat-Standard mehr (Ollama nur für Embeddings bge-m3).
MODE = os.environ.get("MODE", "agent").lower()

# --- Agentenmodus (MODE=agent) ---
# B+-Default: openrouter (Cloud-Denker). "ollama" nur noch für Experimente (nicht empfohlen).
# "fallback" = explizite 3-Stufen-Kette OpenRouter → :free → optional lokal (NICHT B+-Default).
AGENT_PRIMARY_PROVIDER = os.environ.get("AGENT_PRIMARY_PROVIDER", "openrouter")
AGENT_OPENROUTER_MODEL = os.environ.get("AGENT_OPENROUTER_MODEL", "openai/gpt-5.6-luna")
AGENT_OPENROUTER_FALLBACK_MODEL = os.environ.get(
    "AGENT_OPENROUTER_FALLBACK_MODEL", "inclusionai/ling-3.0-flash:free"
)
# Nur relevant wenn PROVIDER=fallback (explizit). B+ nutzt das nicht.
AGENT_LOCAL_FALLBACK_PROVIDER = os.environ.get("AGENT_LOCAL_FALLBACK_PROVIDER", "ollama")

# --- OpenRouter-Chat-Modus (MODE=openrouter-chat) ---
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-5.6-luna")
OPENROUTER_FALLBACK_MODEL = os.environ.get(
    "OPENROUTER_FALLBACK_MODEL", "inclusionai/ling-3.0-flash:free"
)
OPENROUTER_ALLOW_TOOLS = os.environ.get("OPENROUTER_ALLOW_TOOLS", "false").lower() == "true"
OPENROUTER_ALLOW_VAULT = os.environ.get("OPENROUTER_ALLOW_VAULT", "false").lower() == "true"

# Provider-Auswahl:
#   "openrouter" : B+-Standard — Cloud-Denker, kein lokaler Chat-Fallback
#   "fallback"   : nur wenn explizit gesetzt (OpenRouter → free → lokal)
#   "ollama"     : veraltet für Chat (Embeddings laufen separat über bge-m3)
if MODE == "openrouter-chat":
    PROVIDER = "openrouter"
else:
    PROVIDER = AGENT_PRIMARY_PROVIDER

# Ollama: für Chat nur noch optional; Embeddings nutzen OLLAMA_URL + bge-m3 (retrieval.py).
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.5:4b")  # nur bei PROVIDER=ollama/fallback

# OpenRouter (optionales Cloud-Modell). Key aus Umgebung/.env — nicht im Code.
OPENROUTER_URL = os.environ.get("OPENROUTER_URL", "https://openrouter.ai/api/v1")
# OPENROUTER_MODEL schon oben (je Modus): hier Default für Kompatibilität.

# Datenschutz-Schranke für Cloud-Anfragen: max. Zeichen, die an ein externes
# Modell gehen (Tool-Loop kürzt Kontext vor der Übergabe). 0 = unbegrenzt (nicht empfohlen).
EXTERNAL_MAX_CHARS = int(os.environ.get("EXTERNAL_MAX_CHARS", "4000"))

# Geschützte Ordner(namen) im Vault — werden von SUCHEN/LESEN/EDITIEREN ausgeschlossen.
# Ordner, die „private/privats/secrets/health“ usw. heißen oder enthalten, bleiben lokal tabu für den Agenten.
BLOCKED_DIRS = [
    d.lower().strip()
    for d in os.environ.get(
        "BLOCKED_DIRS",
        "private,privat,secrets,health,geheim,persönlich,personenbezogen,recovery,_recovery,recupero",
    ).split(",")
    if d.strip()
]

# Nummerierung für Revisionen: Format "R{laufendeNummer}"
# Wird pro Datei geführt (Datei-Metadaten in einem Sidecar-JSON im Backup-Ordner).

def ensure_dirs():
    """Legt benötigte Verzeichnisse an, falls sie fehlen."""
    for d in (BACKUP_DIR, os.path.dirname(LOG_FILE)):
        os.makedirs(d, exist_ok=True)
    return True
