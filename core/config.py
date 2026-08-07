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

# --- Modell-Runtime (B+, Stand 2026-08-05; CODE-Modus C′ 2026-08-07) ---
# Betriebsart:
#   "agent"          : VaultFind + optional Web, Antwort durch Cloud-Denker (OpenRouter).
#   "openrouter-chat": reine Chat-Oberfläche OHNE Wiki/Tools.
#   "code"           : ^_Code — Datei/Shell-Tools, KEIN VaultFind (DeepSeek via OpenRouter).
# Chat-Denker = ausschließlich OpenRouter. Ollama nur Embeddings (bge-m3).
MODE = os.environ.get("MODE", "agent").lower()

# --- Agentenmodus (MODE=agent) ---
# B+-Default: openrouter = Luna → free bei Ausfall. "fallback" = Alias derselben Kette.
AGENT_PRIMARY_PROVIDER = os.environ.get("AGENT_PRIMARY_PROVIDER", "openrouter")
AGENT_OPENROUTER_MODEL = os.environ.get("AGENT_OPENROUTER_MODEL", "openai/gpt-5.6-luna")
AGENT_OPENROUTER_FALLBACK_MODEL = os.environ.get(
    "AGENT_OPENROUTER_FALLBACK_MODEL", "inclusionai/ling-3.0-flash:free"
)

# --- OpenRouter-Chat-Modus (MODE=openrouter-chat) ---
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-5.6-luna")
OPENROUTER_FALLBACK_MODEL = os.environ.get(
    "OPENROUTER_FALLBACK_MODEL", "inclusionai/ling-3.0-flash:free"
)
OPENROUTER_ALLOW_TOOLS = os.environ.get("OPENROUTER_ALLOW_TOOLS", "false").lower() == "true"
OPENROUTER_ALLOW_VAULT = os.environ.get("OPENROUTER_ALLOW_VAULT", "false").lower() == "true"

# Provider-Auswahl:
#   "openrouter" : B+-Standard — Luna → free
#   "fallback"   : Alias — dieselbe 2-Stufen-Cloud-Kette (kein lokal)
if MODE == "openrouter-chat":
    PROVIDER = "openrouter"
else:
    PROVIDER = AGENT_PRIMARY_PROVIDER

# Ollama nur für Embeddings (bge-m3) in retrieval.py — kein Chat-Modell.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

# OpenRouter. Key aus Umgebung/.env — nicht im Code.
OPENROUTER_URL = os.environ.get("OPENROUTER_URL", "https://openrouter.ai/api/v1")

# Datenschutz-Schranke für Cloud-Anfragen: max. Zeichen, die an ein externes
# Modell gehen (Tool-Loop kürzt Kontext vor der Übergabe). 0 = unbegrenzt (nicht empfohlen).
EXTERNAL_MAX_CHARS = int(os.environ.get("EXTERNAL_MAX_CHARS", "4000"))

# --- CODE-Modus (^_Code / C′) ---
# Denker: DeepSeek V4 Flash 0731 über OpenRouter (kein Anthropic/Claude-Code).
CODE_OPENROUTER_MODEL = os.environ.get(
    "CODE_OPENROUTER_MODEL", "deepseek/deepseek-v4-flash-0731"
)
CODE_OPENROUTER_FALLBACK_MODEL = os.environ.get(
    "CODE_OPENROUTER_FALLBACK_MODEL", "deepseek/deepseek-v4-flash"
)
# Erlaubte Dateisystem-Roots (Komma-getrennt). Default: glyph-ui + glyph-agent.
_HOME = os.path.expanduser("~")
CODE_WORKSPACE_ROOTS = [
    os.path.realpath(p.strip())
    for p in os.environ.get(
        "CODE_WORKSPACE_ROOTS",
        f"{_HOME}/glyph-ui,{_HOME}/glyph-agent",
    ).split(",")
    if p.strip()
]
CODE_BACKUP_DIR = os.environ.get(
    "CODE_BACKUP_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vault", "code_backups"),
)
CODE_SHELL_TIMEOUT = int(os.environ.get("CODE_SHELL_TIMEOUT", "60"))
# Hartes Total-Timeout für OpenRouter-Chat-Calls (Wall-Clock, nicht nur Socket).
# Verhindert endloses Blockieren von resp.read() und damit Server-Einfrieren.
CHAT_TIMEOUT = int(os.environ.get("CHAT_TIMEOUT", "60"))
# CODE-Modus: eigener Override (Default = CHAT_TIMEOUT).
CODE_CHAT_TIMEOUT = int(os.environ.get("CODE_CHAT_TIMEOUT", str(CHAT_TIMEOUT)))
# Shell-Whitelist (Regex, match auf den gesamten Befehl). Nie rm/sudo usw. (Deny in code_tools).
# Env-Override: CODE_SHELL_ALLOW mit Einträgen getrennt durch "||" (Komma bricht |Alternativen).
_CODE_SHELL_DEFAULT = [
    r"^ls(\s|$)",
    r"^pwd$",
    r"^echo(\s|$)",
    r"^cat(\s|$)",
    r"^head(\s|$)",
    r"^tail(\s|$)",
    r"^wc(\s|$)",
    r"^rg(\s|$)",
    r"^grep(\s|$)",
    r"^find(\s|$)",
    r"^git (status|diff|log|show|branch|rev-parse|remote|stash list)(\s|$)",
    r"^npm (test|run|install|ci|ls|view|pack|outdated)(\s|$)",
    r"^npx(\s|$)",
    r"^pytest(\s|$)",
    r"^python3? -m pytest(\s|$)",
    r"^python3? -m unittest(\s|$)",
    r"^python3? --version$",
    r"^node --version$",
    r"^npm --version$",
]
_code_shell_env = os.environ.get("CODE_SHELL_ALLOW", "").strip()
CODE_SHELL_ALLOW = (
    [p.strip() for p in _code_shell_env.split("||") if p.strip()]
    if _code_shell_env
    else list(_CODE_SHELL_DEFAULT)
)
CODE_MAX_ROUNDS = int(os.environ.get("CODE_MAX_ROUNDS", "8"))

# Geschützte Ordner(namen) im Vault — werden von SUCHEN/LESEN/EDITIEREN ausgeschlossen.
BLOCKED_DIRS = [
    d.lower().strip()
    for d in os.environ.get(
        "BLOCKED_DIRS",
        "private,privat,secrets,health,geheim,persönlich,personenbezogen,recovery,_recovery,recupero",
    ).split(",")
    if d.strip()
]


def ensure_dirs():
    """Legt benötigte Verzeichnisse an, falls sie fehlen."""
    for d in (BACKUP_DIR, CODE_BACKUP_DIR, os.path.dirname(LOG_FILE)):
        os.makedirs(d, exist_ok=True)
    return True
