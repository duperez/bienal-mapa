# Mapa Bienal do Livro SP 2026

App pessoal de mapa da 28ª Bienal (Distrito Anhembi, 4–13/09/2026): mapa vetorial
**transcrito** do PDF oficial, offline-first, com busca de expositor e (futuro) rota
entre pontos, com paradas múltiplas.

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
múltiplo mais próximo tem mínimo em **0,194875 m/pt**.

O sinal fica muito mais nítido separando os eixos, que é o que
`tools/anisotropia.py` faz. As ruas correm em X, então o eixo **Y** carrega a
*profundidade* do estande, que é padronizada, enquanto a *frente* (X) é
negociada. Medido só em Y, o mínimo é agudo e profundo em **s=1,0002** — 8,1 cm
de desvio contra 25,0 cm de acaso, com o alias ×2 esperado em s=2,00. As
profundidades mais frequentes saem em **6,0 m (93×), 3,0 m (59×) e 1,0 m (48×)**,
que são medidas de feira; o eixo X segue módulo de painel de 1,2 m.

A escala é dada em metros por ponto do PDF, não como largura do salão: amarrá-la
ao enquadramento fazia a janela de leitura virar régua, e a janela é arbitrária.
Ela hoje é só um filtro (o que é planta, o que é cabeçalho) e tem folga — a
versão anterior cortava 23 pt de estandes reais, que ficavam com coordenada
negativa e apareciam do lado de fora da parede no app.

Reproduzir com `python tools/anisotropia.py` (por eixo, é o que vale) ou
`python tools/calibra.py` (junta os eixos e dilui o sinal). O teste de aceite mede o desvio a cada
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

### Percurso: paradas apontadas, sem GPS

O evento é indoor, sob telhado metálico. O navegador devolve fixes com **10 a
50 m** de erro e o corredor mais largo do pavilhão tem **7 m**: uma posição
errada apontaria a direção errada com toda a confiança do mundo. Posição errada
é pior que posição nenhuma.

Então o visitante **aponta** onde está — por busca ("estou no estande E60", que
é a placa que ele tem na frente dos olhos) ou por toque no mapa, com snap para a
célula caminhável mais próxima. Todas as paradas são simétricas, e a origem fica
sempre escrita na tela: o app nunca roteia de um lugar que o visitante não
escolheu sem ele perceber. Para não cobrar duas marcações no caso comum ("acabei
de entrar, onde fica X"), a origem já vem preenchida com a última usada ou com a
porta mais próxima do destino — e é trocável em um toque.

Isso tem um ganho estrutural além do offline: com todos os pontos escolhidos
sobre o desenho, o erro de georreferência do desenho dentro do prédio (defeitos
4 e 8) **se cancela**. A rota sai certa mesmo com a âncora errada, porque as
paradas vivem no mesmo sistema de coordenadas do traçado. Só a **legenda** em
metros herda o erro de escala.

**Houve uma camada de GPS opcional; foi retirada por decisão explícita do dono
do projeto** ("está dando dor de cabeça demais para uma feature que apesar de
legal, não é incrível"). Ela ordenava candidatos a partir do fix, nunca
filtrava, e vinha com simulação para teste. O aprendizado que ficou: a regra
"porta a menos de 35 m decide sozinha" foi derrubada pelo próprio teste, porque
no meio do salão quase sempre há uma saída nesse raio e o app escolhia por conta
própria um lugar onde o visitante não estava.

### Paradas múltiplas e a melhor ordem

Numa Bienal ninguém vai a um lugar só. O caso real é "quero passar na Companhia
das Letras, na Intrínseca e depois no banheiro", e a ordem em que se faz isso
muda bastante a distância andada. Então o percurso é uma **lista de até 8
paradas**, não um par origem/destino: cada uma pode ser movida (↑ ↓), removida
(×) ou trocada de lugar, e o comprimento de cada trecho aparece **entre** as
duas paradas, que é onde a pergunta nasce.

`Melhor ordem` reordena só as paradas do **meio**: origem e destino ficam
presos, porque são as duas que o visitante escolheu por um motivo — de onde está
e onde quer terminar. Trocá-las seria o app decidindo o passeio dele. A
distância entre pares é a do **A\* sobre a malha, não a linha reta**: num
pavilhão com fileiras de estandes duas coisas a 10 m uma da outra podem ficar a
80 m de caminhada, e é a caminhada que dói no pé. Até 7 paradas do meio a busca
é exaustiva (exata e instantânea); acima disso cai para 2-opt. No teste
automatizado um roteiro de 4 paradas encolheu de **119 m para 57 m** só
reordenando.

No mapa, cada trecho é uma feature própria com cor alternada e setas ao longo do
traçado: com várias paradas, um traço de cor única vira um emaranhado em que não
se enxerga onde um pedaço acaba nem para que lado ir. O roteiro inteiro fica no
`localStorage`, e no carregamento cada ponto lembrado é conferido contra a malha
atual antes de voltar — a grade muda a cada build.

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
4. **A orientação foi resolvida; a posição exata, não.** O desenho entra
   **girado 180 graus**, e isso já está aplicado em `build_map.assentamento()`.
   Três rótulos independentes dizem a mesma coisa, e nenhum depende de parecer
   com alguma forma:

   - a borda de baixo do PDF da Bienal diz `ENTRADA PÚBLICO`; a de cima diz
     `ACESSO SERVIÇO HALL 01..05` com os portões 7, 8 e 9, que a planta
     oficial põe do lado da Marginal. A marquise do público é a face que no
     nosso referencial é o norte, então a borda de baixo tem que ir para lá;
   - o `ACESSO HALL 01` está à direita no PDF, e a planta técnica o põe no
     Expo 01, colado na Alameda de Conexão, que é a face oeste;
   - as três saídas da borda esquerda batem com o Expo 05, único pavilhão
     com sanitários laterais na especificação do Anhembi.

   É rotação, não espelhamento: ninguém imprime mapa espelhado. A métrica de
   distância às marquises preferia o espelhamento (10,2 m contra 26,0 m),
   mas ela não sabe distinguir uma coisa da outra — os rótulos sabem. Por isso
   `tools/afere_ancora.py` parou de caçar orientação: ele agora só **afere** o
   assentamento aplicado, com um critério de duas pontas (porta de público
   perto da marquise, porta de serviço perto da fachada oposta).

   O que sobra é a posição fina. Hoje as 14 portas de público ficam a **28 m**
   da marquise e as 15 de serviço a **74 m** da fachada de trás. Varrendo todos
   os deslocamentos possíveis dentro da folga, nenhum melhora a média: a âncora
   atual já é ótima. O resíduo não é erro de encaixe, é **tamanho** — ver o
   defeito 8. Nada no PDF diz onde o desenho encosta; só uma planta cotada do
   piso resolve isso de vez.

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

8. **A escala está confirmada; o que não fecha é o polígono do prédio.**
   A suspeita de que `ESCALA_M_PT = 0.194875` estivesse 35% pequena caiu com
   medição melhor, e vale registrar por que a suspeita existia: ela vinha de
   duas inferências encadeadas — calibrar o Auditório B da planta técnica em
   0,917 m/pt e multiplicar pela razão dos vãos entre os documentos. O
   Auditório B foi mal medido. Com a escala de hoje o vão real dá 35,9 m e a
   planta técnica sai em 0,676 m/pt, não 0,917.

   O que derruba a suspeita de vez é `tools/anisotropia.py`. Ele separa os
   lados por eixo antes de calibrar, coisa que `calibra.py` não fazia — e a
   diferença importa, porque os dois eixos do desenho não são a mesma coisa.
   As ruas correm em X, então o eixo **Y** carrega a *profundidade* do estande,
   que é padronizada. O eixo Y tem mínimo agudo e profundo em **s=1,0002**
   (8,1 cm contra 25,0 cm de acaso), com o alias ×2 esperado em s=2,00. Se a
   escala estivesse 1,36× errada, as profundidades mais comuns seriam 8,2 m e
   4,1 m; na escala de hoje são **6,0 m (93×), 3,0 m (59×) e 1,0 m (48×)** —
   medidas de feira. O eixo X é mais fraco porque a *frente* é negociada, e
   segue módulo de painel de 1,2 m; testado com 1,2 m e com 0,5 m, o mínimo
   também cai em s≈0,995. `calibra.py` juntava os dois eixos e diluía o sinal.

   O que continua aberto é outra coisa: o desenho mede 290,6 × 143,3 m
   (razão 2,03) e o polígono do OSM mede 322,8 × 224,3 m (razão 1,44). Como o
   desenho é isotrópico e a escala está certa, a conclusão é que **o desenho
   não preenche o `venue.geojson`** — sobram uns 81 m de profundidade. A
   brochura do Anhembi diz "mais de 76 mil m² … dividido em Pavilhão Norte,
   Sul e Oeste", e as cotas oficiais (A 236 m, B 246 m, C 221 m, D 73 m)
   batem com o polígono, não com o desenho. A hipótese é que o polígono seja o
   Pavilhão de Exposições inteiro e a Bienal ocupe só parte dele. Isso também
   explica os cinco `ACESSO HALL`: eles estão a 35,9 m entre si e cobrem 780
   dos 1491 pt de largura, ou seja, são as cinco portas de **um hall**, não os
   cinco pavilhões.

   Consequência prática: as distâncias e os tempos a pé estão certos dentro do
   desenho. O que está errado é a moldura em volta dele.

9. **`MAP_CLIP` corta a borda de cima do desenho.** A janela de leitura começa
   em `y=140` e os rótulos da borda de serviço estão em `y≈112`: perdemos 5
   `ACESSO SERVIÇO HALL` e 5 `SAÍDA DE EMERGÊNCIA`. Como só a borda do público
   sobrou, a aferição da âncora chegou a parecer assimétrica quando não é.

## Layout

```
tools/build_map.py    PDF -> mapa.geojson (transcrição + classificação)
tools/verify_map.py   teste de aceite vetorial contra o PDF
tools/build_route.py  superfície caminhável -> malha.json (grade + acessos)
tools/calibra.py      mede a escala pelo módulo dos estandes
tools/transcribe.py   prova de conceito PDF -> SVG -> PNG
web/                  app MapLibre (Vite + TypeScript)
web/src/rotas.ts      A* sobre a malha, snap e inversa da afim
web/src/percurso.ts   lista de paradas, trechos e a melhor ordem
reference/            PDF oficial e artefatos de comparação
legacy/               app e geradores sintéticos anteriores (referência)
```
