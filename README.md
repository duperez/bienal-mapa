# Mapa Bienal do Livro SP 2026

App pessoal de mapa da 28ª Bienal (Distrito Anhembi, 4–13/09/2026): mapa vetorial
**transcrito** do PDF oficial, offline-first, com busca de expositor e (futuro) rota
entre pontos + GPS.

## A decisão que define o projeto

As tentativas anteriores **sintetizavam** o mapa: partiam de constantes de design
(largura de estande, passo de fileira, gutter) e encaixavam os dados nesse grid.
O erro de cada célula somava com o da vizinha, então o fim da fileira saía longe
do lugar — e cada exceção do PDF real virava um caso especial no gerador.

O pipeline atual **transcreve**: a geometria sai dos paths vetoriais do próprio PDF
(2767 paths, 745 retângulos), em metros, e só depois recebe semântica (categoria,
código, nome) como metadado pendurado por cima. Se a classificação errar, o desenho
continua no lugar certo. O erro para de se propagar.

Consequência prática: o PDF oficial **não desenha a divisa entre estandes vizinhos** —
imprime vários códigos dentro de um retângulo só. Era isso que empurrava para inventar
um grid. A solução é cortar o bloco nos pontos médios reais entre os rótulos
(`subdividir()`), o que mantém o erro **dentro do bloco** em vez de espalhar pela fileira.

## Estado atual

`web/public/data/mapa.geojson` — 438 features geradas do PDF:

```
expositor 202   travessa 48   cultural 19   piso 16   infra 14
patrocinador 8  alimentacao 6 entidade 5    rua 55    rua-eixo 55
POIs: entrada 5, saída 3, escolas 1, entrada-expositor 1
287 com código · 405 com nome
```

Teste de aceite (`tools/verify_map.py`, vetorial com shapely):

```
alimentacao 6/6  cultural 19/19  entidade 5/5  expositor 201/201
infra 14/14  patrocinador 8/8  rua 55/55  travessa 48/48   -> 100%
piso 15/16 (93,8%; a forma restante tem IoU 0,978 - ambiguidade de casamento)
deriva máxima de centroide: 2,37 cm
```

App (`web/`): MapLibre GL 100% local (nenhum tile ou fonte externa), pavilhão real do
Anhembi (OSM way 203621978) como base, busca, seleção com bottom sheet, ícones de POI
desenhados em canvas. Screenshots de verificação em `web/shot-*.png`.

## Como rodar

```bash
python3 -m venv .venv && .venv/bin/pip install -r tools/requirements.txt
sh tools/build.sh            # PDF -> mapa.geojson + teste de aceite
sh tools/build.sh --aceitar  # regrava a baseline (só quando a mudança for intencional)

cd web && npm install && npm run dev
node test-shots.mjs <porta>  # screenshots do app real via Playwright
```

`tools/transcribe.py` gera a prova de conceito da transcrição
(`reference/transcrito.png`, 89,6% dos pixels idênticos ao PDF, IoU 0,92) — serve
para conferir a olho que a leitura do PDF está correta.

## O que ainda não está resolvido

1. **`data/structure.json` é o único insumo que não vem do PDF** — fornece o
   diretório (código → nome do expositor) e os nomes da Travessa. Veio da extração
   legada; não foi reauditado.
2. **Numeração TL01–TL48 é derivada**, não impressa no PDF. As features carregam
   `numeracao_derivada: true`. Se estiver errada, troca-se o rótulo, não o desenho.
3. **12 estandes sem código** e 12 áreas de infra sem nome — o PDF não imprime.
   Hoje ficam sem rótulo no app (melhor que rótulo inventado).
4. **GPS não calibrado**: a afim atual ancora o canto NW no polígono OSM e usa o lado
   maior do hall (322 m) como escala. Serve para o desenho; não foi validada contra
   leitura de GPS real no local.
5. **Rota (fase 2)**: não existe grafo no pipeline novo. O grafo do legado
   (`legacy/`) não foi portado.
6. **Deploy https** (Pages ou similar) para service worker e geolocalização valerem.

## Layout

```
tools/build_map.py    PDF -> mapa.geojson (transcrição + classificação)
tools/verify_map.py   teste de aceite vetorial contra o PDF
tools/transcribe.py   prova de conceito PDF -> SVG -> PNG
web/                  app MapLibre (Vite + TypeScript)
reference/            PDF oficial e artefatos de comparação
legacy/               app e geradores sintéticos anteriores (referência)
```
