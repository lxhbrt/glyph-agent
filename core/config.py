# -*- coding: utf-8 -*-
"""
Konfiguration des persönlichen lokalen Assistenten (glyph-agent).

Diese Datei ist der EINZIGE Ort, an dem der Vault-Pfad zentral gesetzt wird.
Nicht in anderen Dateien hart verdrahten — siehe Architektur-Regel.
"""
import os

# --- Vault-Pfade ---
# Live-SoT ist die Registry (~/.glyph/vaults.json via vaults_registry).
# Import-Default bleibt leer — reload_vault_paths() / apply_to_config() füllt.
VAULT_PATHS = []
VAULT_PATH = ""


def reload_vault_paths():
    """Hot-Reload aus ~/.glyph/vaults.json (Kabelsalat)."""
    global VAULT_PATHS, VAULT_PATH
    try:
        from . import vaults_registry as _vr

        paths = _vr.apply_to_config()
        return paths
    except Exception:
        return list(VAULT_PATHS)

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
# B+-Default: openrouter = DeepSeek V4 Flash → free bei Ausfall. "fallback" = Alias derselben Kette.
AGENT_PRIMARY_PROVIDER = os.environ.get("AGENT_PRIMARY_PROVIDER", "openrouter")
AGENT_OPENROUTER_MODEL = os.environ.get(
    "AGENT_OPENROUTER_MODEL", "deepseek/deepseek-v4-flash-0731"
)
AGENT_OPENROUTER_FALLBACK_MODEL = os.environ.get(
    "AGENT_OPENROUTER_FALLBACK_MODEL", "inclusionai/ling-3.0-flash:free"
)

# --- OpenRouter-Chat-Modus (MODE=openrouter-chat) ---
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-v4-flash-0731")
OPENROUTER_FALLBACK_MODEL = os.environ.get(
    "OPENROUTER_FALLBACK_MODEL", "inclusionai/ling-3.0-flash:free"
)
OPENROUTER_ALLOW_TOOLS = os.environ.get("OPENROUTER_ALLOW_TOOLS", "false").lower() == "true"
OPENROUTER_ALLOW_VAULT = os.environ.get("OPENROUTER_ALLOW_VAULT", "false").lower() == "true"

# Provider-Auswahl:
#   "openrouter" : B+-Standard — DeepSeek V4 Flash → free
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
# Screenshots/Bilder: DeepSeek Flash hat oft keine Vision — Luna separat (oder Override).
CODE_VISION_MODEL = os.environ.get("CODE_VISION_MODEL", "openai/gpt-5.6-luna")
# Erlaubte Dateisystem-Roots (Komma-getrennt). Nur existierende Dirs nach expanduser.
# Default: glyph-ui, glyph-agent, ~/.openclaw/workspace; optional ~/grok-chat-ui wenn vorhanden.
_HOME = os.path.expanduser("~")
_CODE_ROOTS_DEFAULT_CANDIDATES = [
    f"{_HOME}/glyph-ui",
    f"{_HOME}/glyph-agent",
    f"{_HOME}/.openclaw/workspace",
    f"{_HOME}/grok-chat-ui",  # optional — nur wenn Dir existiert
]


def _filter_existing_roots(candidates):
    """Expandiert Pfade und behält nur existierende Verzeichnisse (realpath)."""
    out = []
    seen = set()
    for p in candidates or []:
        p = (p or "").strip()
        if not p:
            continue
        try:
            expanded = os.path.expanduser(p)
            if not os.path.isdir(expanded):
                continue
            real = os.path.realpath(expanded)
        except OSError:
            continue
        if real in seen:
            continue
        seen.add(real)
        out.append(real)
    return out


_code_roots_env = os.environ.get("CODE_WORKSPACE_ROOTS", "").strip()
if _code_roots_env:
    _code_root_candidates = [p.strip() for p in _code_roots_env.split(",") if p.strip()]
else:
    _code_root_candidates = list(_CODE_ROOTS_DEFAULT_CANDIDATES)
CODE_WORKSPACE_ROOTS = _filter_existing_roots(_code_root_candidates)
# Wenn true (Default): alle Datei-Tools bleiben roots-only (v1: immer roots-only).
# Env nur dokumentiert/reserviert — Escapes außerhalb der Roots bleiben verboten.
CODE_WORKSPACE_ONLY = os.environ.get("CODE_WORKSPACE_ONLY", "true").lower() in (
    "1", "true", "yes", "on",
)
# SoT ~/.glyph/workspaces.json (Modes r/rw/private). Tests können False setzen.
CODE_WORKSPACES_USE_REGISTRY = os.environ.get(
    "CODE_WORKSPACES_USE_REGISTRY", "true"
).lower() in ("1", "true", "yes", "on")
CODE_BACKUP_DIR = os.environ.get(
    "CODE_BACKUP_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vault", "code_backups"),
)
CODE_SHELL_TIMEOUT = int(os.environ.get("CODE_SHELL_TIMEOUT", "60"))
# Hartes Total-Timeout für OpenRouter-Chat-Calls (Wall-Clock, nicht nur Socket).
# Verhindert endloses Blockieren von resp.read() und damit Server-Einfrieren.
CHAT_TIMEOUT = int(os.environ.get("CHAT_TIMEOUT", "60"))
# CODE-Modus: eigener Override. Multi-Round + Diffs brauchen mehr als 60s —
# Default 180s (vorher = CHAT_TIMEOUT und brach oft mitten in Tool-Ketten ab).
CODE_CHAT_TIMEOUT = int(os.environ.get("CODE_CHAT_TIMEOUT", "180"))
# Shell-Whitelist (Regex, match auf den gesamten Befehl). Nie rm/sudo/push usw. (Deny in code_tools).
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
    r"^diff(\s|$)",
    r"^mkdir(\s|$)",
    r"^touch(\s|$)",
    r"^cp(\s|$)",
    # git: read + add/commit/stash — KEIN push/pull/fetch (Deny + kein Allow)
    r"^git (status|diff|log|show|branch|rev-parse|remote)(\s|$)",
    r"^git add(\s|$)",
    r"^git commit(\s|$)",
    r"^git stash(\s|$)",
    r"^npm (test|run|install|ci|ls|view|pack|outdated)(\s|$)",
    r"^npx(\s|$)",
    r"^pytest(\s|$)",
    r"^python3? -m pytest(\s|$)",
    r"^python3? -m unittest(\s|$)",
    r"^python3? --version$",
    # python3/node: Script-Datei oder -m Modul (cwd unter Root)
    r"^python3?(\s+\S+\.py|\s+-m\s)",
    r"^node --version$",
    r"^node(\s+\S+\.(js|mjs|cjs))",
    r"^npm --version$",
]
_code_shell_env = os.environ.get("CODE_SHELL_ALLOW", "").strip()
CODE_SHELL_ALLOW = (
    [p.strip() for p in _code_shell_env.split("||") if p.strip()]
    if _code_shell_env
    else list(_CODE_SHELL_DEFAULT)
)
CODE_MAX_ROUNDS = int(os.environ.get("CODE_MAX_ROUNDS", "16"))

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
