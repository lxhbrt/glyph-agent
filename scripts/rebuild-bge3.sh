#!/bin/bash
# Automatischer bge-m3 Index-Rebuild (2026-08-03)
# 1) Wartet, bis bge-m3 in Ollama verfügbar ist
# 2) Setzt EMBED_MODEL=bge-m3
# 3) Baut den Vault-Index komplett neu (2968+ Chunks)
# 4) Testet die MOC-Frage (Arbeitsschutz vs. Arbeitssicherheit)
# Log: /tmp/bge3_rebuild.log

LOG=/tmp/bge3_rebuild.log
cd ~/glyph-agent || exit 1

echo "=== bge-m3 Rebuild Start: $(date) ===" > "$LOG"

# 1) Warten bis bge-m3 da ist (max 15 Min)
for i in $(seq 1 45); do
  if ollama list 2>/dev/null | grep -q "^bge-m3"; then
    echo "bge-m3 verfügbar nach ${i}x20s" >> "$LOG"
    break
  fi
  sleep 20
done

if ! ollama list 2>/dev/null | grep -q "^bge-m3"; then
  echo "FEHLER: bge-m3 nach 15 Min nicht verfügbar" >> "$LOG"
  exit 2
fi

# 2) EMBED_MODEL setzen (für den Prozess, nicht persistent in .env — 
#    die .env ändere ich separat, damit der Dienst danach auch damit läuft)
export EMBED_MODEL=bge-m3

# 3) Index komplett neu aufbauen (altes Embedding weg)
echo "=== Alten Index entfernen (nomic) ===" >> "$LOG"
rm -f logs/vault_index.json
echo "=== Rebuild mit bge-m3 ===" >> "$LOG"
python3 -c "
import sys; sys.path.insert(0,'.')
from core import retrieval
import os
os.environ['EMBED_MODEL']='bge-m3'
stats = retrieval.build_index_from_vault()
print('discovered:', stats.get('discovered'))
print('indexed:', stats.get('indexed'))
print('chunks:', stats.get('chunks'))
print('failed:', stats.get('failed'))
print('duration_s:', stats.get('duration_s'))
" >> "$LOG" 2>&1

# 4) MOC-Frage testen
echo "=== MOC-Frage Test (bge-m3) ===" >> "$LOG"
python3 -c "
import sys; sys.path.insert(0,'.')
from core import retrieval
import os
os.environ['EMBED_MODEL']='bge-m3'
res = retrieval.search('Was ist der Unterschied zwischen Arbeitsschutz und Arbeitssicherheit?', top_k=10)
print('Status:', res.get('status'), '| Selected:', res.get('selected'))
for i, r in enumerate(res.get('results', [])[:10], 1):
    p = r.get('path','')
    star = ' <<< MOC' if '00 MOC - Arbeitssicherheit' in p else ''
    print(f'  #{i} hybrid={r.get(\"score\"):.3f} | {p[:70]}{star}')
" >> "$LOG" 2>&1

echo "=== bge-m3 Rebuild Ende: $(date) ===" >> "$LOG"
