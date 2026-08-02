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
# Provider-Auswahl (austauschbar): "ollama" (lokal, Standard) | "openrouter" | "fallback"
#  - "ollama"     : nur lokales Qwen (offline, kostenlos, DSGVO-sicher)
#  - "openrouter" : nur Cloud-Modell (kostenpflichtig; nur Tool-Loop-minimierte Ausschnitte)
#  - "fallback"   : erst OpenRouter, bei Fehler automatisch lokal (Resilienz)
# Der Modell-Adapter ist austauschbar; die Agenten-/Tool-Architektur bleibt.
PROVIDER = os.environ.get("HSEQ_PROVIDER", "ollama")

# Ollama läuft lokal auf localhost:11434. Modellname = auswählbar.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen-solid")

# OpenRouter (optionales Cloud-Modell). Key aus Umgebung/.env — nicht im Code.
OPENROUTER_URL = os.environ.get("OPENROUTER_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-chat")

# Datenschutz-Schranke für Cloud-Anfragen: max. Zeichen, die an ein externes
# Modell gehen (Tool-Loop kürzt Kontext vor der Übergabe). 0 = unbegrenzt (nicht empfohlen).
EXTERNAL_MAX_CHARS = int(os.environ.get("EXTERNAL_MAX_CHARS", "4000"))

# Nummerierung für Revisionen: Format "R{laufendeNummer}"
# Wird pro Datei geführt (Datei-Metadaten in einem Sidecar-JSON im Backup-Ordner).

def ensure_dirs():
    """Legt benötigte Verzeichnisse an, falls sie fehlen."""
    for d in (BACKUP_DIR, os.path.dirname(LOG_FILE)):
        os.makedirs(d, exist_ok=True)
    return True
