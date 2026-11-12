#!/usr/bin/env bash
# Arranca el bot en local usando .env y un entorno virtual
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || { echo "Copia .env.example a .env y pon tu TOKEN"; exit 1; }
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
set -a; source .env; set +a
exec .venv/bin/python punsbot.py
