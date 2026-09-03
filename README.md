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

`web/public/data/mapa.geojson` — 408 features geradas do PDF:

```
expositor 199   travessa 48   cultural 17   piso 19   infra 10
patrocinador 7  alimentacao 6 entidade 5    rua 55    via 26   circulacao 2
POIs: entrada 6, saída 6, escolas 1, entrada-expositor 1
282 com código · 367 com nome
```

Teste de aceite (`tools/verify_map.py`, vetorial com shapely):

```
alimentacao 6/6  cultural 17/17  entidade 5/5  expositor 198/198
infra 10/10  patrocinador 7/7  rua 55/55  travessa 48/48   -> 100%
piso 18/19 (94,7%; a forma restante tem IoU 0,957 - ambiguidade de casamento)
deriva máxima de centroide: 2,17 cm

vias: 26, sendo as 14 ruas nomeadas no PDF
nenhuma via atravessa bloco · 0/286 blocos navegáveis sem circulação ao lado
escala: desvio ao módulo de 1 m = 13,8 cm em 1173 lados (acaso seria 25,0 cm)
fora do prédio: 0 blocos
```

### Escala

A escala do desenho não podia sair do prédio: o PDF da Bienal é peça de
divulgação, é cortado à esquerda e no rodapé, e nem nomeia o local. Casar a
largura do recorte com os 322 m do Distrito Anhembi era palpite — e estava 11%
grande.

O que resolveu foi evidência interna. Estande de feira é modular: as frentes são
múltiplos inteiros de 1 m. Varrendo a escala, o desvio médio dos lados ao
múltiplo mais próximo tem mínimo único e agudo em **0,194875 m/pt** (13,8 cm,
contra 24,8 cm na escala antiga — indistinguível de sorteio). Duas conferências
que não entram na conta concordam: o lado mais frequente vira **6,01 m** (frente
padrão de estande) e os cinco Acessos Hall ficam a **36,2 m** entre si (vão
estrutural).

A escala é dada em metros por ponto do PDF, não como largura do salão: amarrá-la
ao enquadramento fazia a janela de leitura virar régua, e a janela é arbitrária.
Ela hoje é só um filtro (o que é planta, o que é cabeçalho) e tem folga — a
versão anterior cortava 23 pt de estandes reais, que ficavam com coordenada
negativa e apareciam do lado de fora da parede no app.

Reproduzir com `python tools/calibra.py`. O teste de aceite mede o desvio a cada
build, então a escala não pode regredir em silêncio.

### Rota

O visitante pergunta "como chego lá", então existe `web/public/data/malha.json`:
a superfície caminhável amostrada a cada **0,5 m** (601 x 300 células, 75.938
livres) mais o ponto de acesso de cada bloco. O A* roda **no navegador** — a
origem de uma rota é o visitante, e ela muda a cada passo.

Grade em vez de grafo das vias porque as vias são o *rótulo* dos corredores, não
a topologia deles: não se nodam nos cruzamentos, não chegam à porta do estande e
não cobrem praça nem avental. Costurar isso à mão é justamente o que o projeto
se proíbe. A grade é a própria superfície livre, amostrada.

```
282 destinos · 0 ilhados das portas
300 pares estande->estande · 0 sem rota · mediana 108 m · máx 281 m
7,1 curvas por rota · 1,5 ms por par
malha.json: 34,1 KB
```

Detalhes que custaram cuidado: diagonal só passa se os dois ortogonais também
estiverem livres (senão a rota corta a quina do estande); e o caminho cru é uma
escada de 0,5 m, enxugada por varredura de visibilidade — sem isso o traço sai
serrilhado e daria um "vire à esquerda" a cada meio metro.

### Percurso: por que o GPS não manda

O evento é indoor, sob telhado metálico. O navegador devolve fixes com **10 a
50 m** de erro e o corredor mais largo do pavilhão tem **7 m**: uma posição
errada apontaria a direção errada com toda a confiança do mundo. Posição errada
é pior que posição nenhuma.

Então o visitante **aponta** onde está — por busca ("estou no estande E60", que
é a placa que ele tem na frente dos olhos) ou por toque no mapa, com snap para a
célula caminhável mais próxima. Origem e destino são simétricos, e a origem fica
sempre escrita na tela: o app nunca roteia de um lugar que o visitante não
escolheu sem ele perceber. Para não cobrar duas marcações no caso comum ("acabei
de entrar, onde fica X"), a origem já vem preenchida com a última usada ou com a
porta mais próxima do destino — e é trocável em um toque.

O GPS entra como camada opcional, e mesmo assim para **ordenar** candidatos,
nunca para filtrar. O motivo é o defeito 4: a âncora do desenho dentro do prédio
tem ~30 m de folga, então um raio traçado a partir do fix sairia descentrado por
mais do que o próprio erro do sensor e poderia excluir justamente o estande
certo. Ordenando, o erro de âncora piora a ordem da lista e nunca esconde a
resposta. Regras: fix acima de 100 m de erro é descartado; espera de 5 s com relógio
próprio e cai para o manual (fix pendurado — nem sucesso nem erro — é o desfecho
mais comum indoor, e o `timeout` da API nem sempre é respeitado); e o GPS só
decide sozinho quando **uma porta é a coisa mais próxima do fix**. Essa última
regra começou como "porta a menos de 35 m" e o teste derrubou: no meio do salão
quase sempre há uma saída nesse raio, e o app escolhia por conta própria um
lugar onde o visitante não estava.

Como o GPS não dá para exercitar sentado, `web/src/gps.ts` isola a leitura de
posição e aceita simulação por `?gps=sim` (shift+clique larga um fix, `&erro=NN`
define a precisão fingida). A simulação é sempre visível — tarja roxa na tela,
rótulo do botão trocado e "· simulado" na mensagem —, porque um fix falso
passando por verdadeiro seria o pior defeito possível neste app.

`test-gps.mjs` cobre 8 cenários com a emulação de geolocalização do próprio
navegador (não com o modo de simulação): fix na porta, fix no meio do salão,
sinal fraco, fora do pavilhão, permissão negada, fix pendurado e a simulação
se anunciando.

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
sh tools/build.sh            # PDF -> mapa.geojson + malha.json + teste de aceite
sh tools/build.sh --aceitar  # regrava a baseline (só quando a mudança for intencional)

cd web && npm install && npm run dev
node test-shots.mjs <porta>  # screenshots do app real via Playwright
node test-rota.mjs <porta>   # percurso na UI + carga de 300 pares de estandes
node test-gps.mjs <porta>    # 8 cenários de GPS com emulação real do navegador

# testar GPS à mão, sem estar no Anhembi: shift+clique larga um fix falso
open 'http://localhost:5173/?gps=sim&erro=25'
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
   desenho ocupa 293 x 149 m dentro de um prédio de 323 x 224 m. A regra está
   declarada em `build_map.ancora()` — o bloco desenhado mais a noroeste encosta
   no canto noroeste do prédio — e o teste cobra a consequência (0 blocos fora
   do prédio). Mas o desenho oficial sai da página à esquerda (blocos de serviço
   aparecem cortados na borda), então sobram ~30 m em x e ~75 m em y sem
   explicação: o canto certo pode ser o NE. Faltam pontos de controle — tentei
   sanitários, portões e contorno da planta oficial do Anhembi e nenhum casou,
   porque o mapa da Bienal não desenha nenhuma feição permanente do prédio.
   Resolver com leitura de GPS no local.
5. **Rota sem instrução falada**: o caminho existe, é ótimo e já vai de
   qualquer ponto a qualquer ponto, mas o app só desenha a linha. Falta cruzar
   os trechos com as vias para escrever "siga pela RUA E, vire na Transversal
   04".
6. **`LARG_MIN = 2 m` e `AVENTAL = 6 m` são julgamento meu**, não saem do PDF.
   As 9 transversais e 1 alameda sem seta carregam `nome_derivado: true`; a RUA
   AA corre na borda do anexo e carrega `borda_aberta: true`.
7. **Não abre offline ainda.** Todos os assets já são locais (~650 KB, nenhum
   tile ou fonte externa) e o roteamento não faz uma única chamada de rede, mas
   não há service worker: `main.ts` hoje só *desregistra* os SW residuais do app
   legado. Falta escrever o SW próprio e publicar em https (Pages ou similar) —
   sem isso, e sem https, nem o cache nem a geolocalização valem.

## Layout

```
tools/build_map.py    PDF -> mapa.geojson (transcrição + classificação)
tools/verify_map.py   teste de aceite vetorial contra o PDF
tools/build_route.py  superfície caminhável -> malha.json (grade + acessos)
tools/calibra.py      mede a escala pelo módulo dos estandes
tools/transcribe.py   prova de conceito PDF -> SVG -> PNG
web/                  app MapLibre (Vite + TypeScript)
web/src/rotas.ts      A* sobre a malha, snap e inversa da afim
web/src/percurso.ts   escolha de origem/destino e camada opcional de GPS
web/src/gps.ts        leitura de posição, com simulação para teste
reference/            PDF oficial e artefatos de comparação
legacy/               app e geradores sintéticos anteriores (referência)
```
