#!/bin/sh
# Build completo: extração -> grafo -> app (map.json + service worker versionado).
set -e
cd "$(dirname "$0")/.."

.venv/bin/python tools/build_map.py
.venv/bin/python tools/build_layout.py
.venv/bin/python tools/build_graph.py
cp data/map.json app/map.json

# versiona o cache do SW com o hash do conteúdo (muda -> SW reinstala e renova o cache)
V=$(cat app/map.json app/index.html | shasum | cut -c1-10)
sed "s/__V__/$V/" tools/sw.template.js > app/sw.js
echo "build ok — versão do cache do service worker: bienal-$V"
