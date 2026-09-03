#!/bin/sh
# PDF oficial -> web/public/data/mapa.geojson, com teste de aceite.
# O build só é considerado bom se a geometria continuar batendo com o PDF.
set -e
cd "$(dirname "$0")/.."

PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY=python3

"$PY" tools/build_map.py
"$PY" tools/verify_map.py "$@"
