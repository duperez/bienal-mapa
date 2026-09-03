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

A outra pegadinha: patrocinadores e atividades culturais são desenhados como
**prismas "3D"**. A face de topo — a que tem a cor da legenda — fica ~1,4 m acima e
à esquerda da posição real; a área ocupada é a **base**. `desextrudar()` reconhece o
prisma pelas duas faces auxiliares e translada o topo para cima da base, o que põe
esses blocos de volta na fileira.

## Estado atual

`web/public/data/mapa.geojson` — 400 features geradas do PDF:

```
expositor 199   travessa 48   cultural 17   piso 16   infra 10
patrocinador 7  alimentacao 6 entidade 5    rua 55    via 25   circulacao 2
POIs: entrada 5, saída 3, escolas 1, entrada-expositor 1
282 com código · 366 com nome
```

Teste de aceite (`tools/verify_map.py`, vetorial com shapely):

```
alimentacao 6/6  cultural 17/17  entidade 5/5  expositor 198/198
infra 10/10  patrocinador 7/7  rua 55/55  travessa 48/48   -> 100%
piso 15/16 (93,8%; a forma restante tem IoU 0,979 - ambiguidade de casamento)
deriva máxima de centroide: 2,07 cm

vias: 25, sendo as 14 ruas nomeadas no PDF
nenhuma via atravessa bloco · 0/286 blocos navegáveis sem circulação ao lado
escala: desvio ao módulo de 1 m = 13,8 cm em 1173 lados (acaso seria 25,0 cm)
```

### Escala

A escala do desenho não podia sair do prédio: o PDF da Bienal é peça de
divulgação, é cortado à esquerda e no rodapé, e nem nomeia o local. Casar a
largura do recorte com os 322 m do Distrito Anhembi era palpite — e estava 11%
grande.

O que resolveu foi evidência interna. Estande de feira é modular: as frentes são
múltiplos inteiros de 1 m. Varrendo a escala, o desvio médio dos lados ao
múltiplo mais próximo tem mínimo único e agudo em **289,0 m** (13,8 cm, contra
24,8 cm nos 322 m — indistinguível de sorteio). Duas conferências que não entram
na conta concordam: o lado mais frequente vira **6,01 m** (frente padrão de
estande) e os cinco Acessos Hall ficam a **36,2 m** entre si (vão estrutural).

Reproduzir com `python tools/calibra.py`. O teste de aceite mede o desvio a cada
build, então a escala não pode regredir em silêncio.

### Ruas e circulação

O PDF não desenha ruas: desenha setas com o nome delas. As setas cobrem só 9,7%
do espaço livre — a seta é o rótulo da rua, não a rua. Então a circulação é
derivada por morfologia (fecho de 12 m sobre os blocos, menos os blocos, com
abertura de 2 m) e as vias saem da largura local do vão, entre 2 e 12 m. Uma
seta que a varredura não alcança vira semente: o PDF afirma que a rua existe,
então ela entra pelo corredor que passa por baixo da seta. Nada é desenhado à
mão — se um corredor sair errado, conserta-se a regra.

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
3. **Estandes sem código** e áreas de infra sem nome — o PDF não imprime.
   Hoje ficam sem rótulo no app (melhor que rótulo inventado).
4. **A âncora ainda é palpite, só a escala foi medida.** Na escala correta o
   desenho ocupa 289 x 145 m dentro de um prédio de 319 x 236 m, e a afim
   encosta o canto NW dele no canto NW do polígono OSM. Mas o desenho é cortado
   à esquerda e no rodapé, então sobram 30 m em x e 90 m em y sem explicação: o
   canto certo pode ser o NE. Faltam pontos de controle — tentei sanitários,
   portões e contorno da planta oficial do Anhembi e nenhum casou, porque o mapa
   da Bienal não desenha nenhuma feição permanente do prédio. Resolver com
   leitura de GPS no local.
5. **Rota (fase 2)**: as vias existem como LineString, mas ainda não há grafo
   nodado nos cruzamentos nem ponto de acesso por estande.
6. **`LARG_MIN = 2 m` e `AVENTAL = 6 m` são julgamento meu**, não saem do PDF.
   As 9 transversais e 1 alameda sem seta carregam `nome_derivado: true`; a RUA
   AA corre na borda do anexo e carrega `borda_aberta: true`.
7. **Deploy https** (Pages ou similar) para service worker e geolocalização valerem.

## Layout

```
tools/build_map.py    PDF -> mapa.geojson (transcrição + classificação)
tools/verify_map.py   teste de aceite vetorial contra o PDF
tools/transcribe.py   prova de conceito PDF -> SVG -> PNG
web/                  app MapLibre (Vite + TypeScript)
reference/            PDF oficial e artefatos de comparação
legacy/               app e geradores sintéticos anteriores (referência)
```
