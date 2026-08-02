# -*- coding: utf-8 -*-
"""
Konfiguration des persönlichen lokalen Assistenten (glyph-agent).

Diese Datei ist der EINZIGE Ort, an dem der Vault-Pfad zentral gesetzt wird.
Nicht in anderen Dateien hart verdrahten — siehe Architektur-Regel.
"""
import os

# --- Zentrale Pfad-Konfiguration (fest, persönlicher Sandkasten) ---
# Der primäre Vault, mit dem der Assistent arbeitet.
VAULT_PATH = "/Users/lxndrhbrt/ObsidianVaults/HSEQ Sync"

# Backup-Verzeichnis für Revisionen (vor jeder Schreib-Änderung).
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vault", "backups")

# Protokoll-/Log-Datei (JSON-Lines) für alle Aktionen.
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", "actions.jsonl")

# --- Modell-Runtime ---
# Betriebsart (klar getrennt, zwei Modi):
#   "agent"         : Agentenmodus — lokaler Agent (Qwen) greift auf Wiki/Tools zu,
#                     OpenRouter formuliert bevorzugt; Fallback-Kette im Agentenmodus:
#                     bevorzugtes OpenRouter-Modell -> kostenloses OpenRouter-Modell -> Qwen lokal.
#   "openrouter-chat": reine Chat-Oberfläche OHNE Wiki-/Tool-/Vault-Zugriff; nur OpenRouter,
#                     optional Fallback auf ein kostenloses OpenRouter-Modell (KEIN Qwen-Wechsel).
MODE = os.environ.get("MODE", "agent").lower()

# --- Agentenmodus (MODE=agent): Provider- und Fallback-Kette ---
# AGENT_PRIMARY_PROVIDER: "openrouter" (bevorzugt) | "ollama" (lokal, kein Cloud-Versuch)
AGENT_PRIMARY_PROVIDER = os.environ.get("AGENT_PRIMARY_PROVIDER", "ollama")
# Bevorzugtes OpenRouter-Modell für den Agentenmodus.
AGENT_OPENROUTER_MODEL = os.environ.get("AGENT_OPENROUTER_MODEL", "deepseek/deepseek-chat")
# Kostenloses OpenRouter-Fallback-Modell (Modellwechsel INNERHALB von OpenRouter).
# Verifizierte, real existierende :free-ID (via OpenRouter /models):
AGENT_OPENROUTER_FALLBACK_MODEL = os.environ.get("AGENT_OPENROUTER_FALLBACK_MODEL", "inclusionai/ling-3.0-flash:free")
# Lokaler Fallback (nur Agentenmodus): wenn OpenRouter insgesamt ausfällt -> lokales Modell.
AGENT_LOCAL_FALLBACK_PROVIDER = os.environ.get("AGENT_LOCAL_FALLBACK_PROVIDER", "ollama")

# --- OpenRouter-Chat-Modus (MODE=openrouter-chat) ---
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-chat")
OPENROUTER_FALLBACK_MODEL = os.environ.get("OPENROUTER_FALLBACK_MODEL", "inclusionai/ling-3.0-flash:free")
# Im OpenRouter-Chat-Modus sind Tools/Vault IMMER deaktiviert (sichere Defaults, überschreibbar
# nur, falls du es bewusst anders willst — nicht empfohlen):
OPENROUTER_ALLOW_TOOLS = os.environ.get("OPENROUTER_ALLOW_TOOLS", "false").lower() == "true"
OPENROUTER_ALLOW_VAULT = os.environ.get("OPENROUTER_ALLOW_VAULT", "false").lower() == "true"

# Provider-Auswahl (intern, kompatibel zur bisherigen Schnittstelle):
#   "ollama"     : nur lokales Qwen (offline, kostenlos, DSGVO-sicher)
#   "openrouter" : nur Cloud-Modell (kostenpflichtig; nur Tool-Loop-minimierte Ausschnitte)
#   "fallback"   : erst OpenRouter (mit gratis-Modell-Stufe), bei Gesamtfehler automatisch lokal
# Im Agentenmodus wird AGENT_PRIMARY_PROVIDER verwendet; im openrouter-chat nur openrouter.
if MODE == "openrouter-chat":
    PROVIDER = "openrouter"
else:  # agent
    PROVIDER = AGENT_PRIMARY_PROVIDER

# Ollama läuft lokal auf localhost:11434. Modellname = auswählbar.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen-solid")

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
        "private,privat,secrets,health,geheim,persönlich,personenbezogen",
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
