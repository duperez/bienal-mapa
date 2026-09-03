#!/bin/sh
# PDF oficial -> mapa.geojson + malha.json, com teste de aceite.
# O build só é considerado bom se a geometria continuar batendo com o PDF e se
# todo estande continuar alcançável a partir de uma porta do evento.
set -e
cd "$(dirname "$0")/.."

PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY=python3

"$PY" tools/build_map.py
"$PY" tools/verify_map.py "$@"
"$PY" tools/build_route.py
