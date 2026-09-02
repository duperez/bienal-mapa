# Design system — Mapa Bienal 2026

Proposta original pesquisada pelo agente `web-ui-designer` (referências: Google/Apple
indoor maps, Mappedin, ExpoFP/Map Your Show, Heathrow/Changi), revisada em 2026-09-01
depois de teste real no celular (rótulos pequenos demais, cores difíceis de diferenciar,
ruas sem parecer via). Princípio central mantido: **cor é informação, não decoração** —
mas a execução ficou mais saturada/explícita do que a proposta original (mais contraste,
menos sutileza), porque em uso real ao ar livre a sutileza "mapa profissional" não leu bem
numa tela pequena. Amarelo Bienal `#FFD200` = seleção/busca. Estandes comuns são brancos —
pintar todos por categoria é o erro do mapa oficial.

## Tokens (light / dark)

| Token | Light | Dark | Papel |
|---|---|---|---|
| `--map-canvas` | `#E4E1DB` | `#0C0D10` | fora do pavilhão |
| `--map-hall` | `#EDEBE7` | `#111214` | piso/corredores |
| `--street-fill` / `--street-stroke` | `#DDD6C8` / `#C2B9A4` | `#1B1D21` / `#33363D` | rua (via desenhada, não espaço negativo) |
| `--booth-fill` | `#FFFFFF` | `#26282E` | estande normal |
| `--booth-stroke` | `#D3CFC7` | `#3A3D45` | borda 0.5–0.75px |
| `--block-stroke` | `#B9B4AA` | `#4A4E58` | contorno de quadra |
| `--wall` | `#9B968C` | `#565B66` | perímetro, 2px |
| `--sel-fill` / `--sel-stroke` | `#FFD200` / `#8A7000` | idem | selecionado |
| `--res-fill` / `--res-stroke` | `#FFF3BF` / `#D9B200` | `#4A4020` / idem | resultado de busca |
| `--food-fill` / `--food-stroke` / `--food-text` | `#FFDCA8` / `#B36B00` / `#7A4100` | `#4A3013` / `#D98C2B` / `#F5B942` | área de alimentação |
| `--cult-fill` / `--cult-stroke` / `--cult-text` | `#B9E0F2` / `#0072A8` / `#00516E` | `#123244` / `#4FA9D6` / `#7FCBEF` | área cultural/arena |
| `--svc-fill` / `--svc-text` | `#8A6FBF` / `#FFFFFF` | `#9A82CF` / `#17121F` | marcador de serviço/infra (círculo + glifo "i", **sem** preenchimento de área) |
| `--you` | `#1A73E8` | `#8AB4F8` | blue dot + halo 15–18% |
| `--surface` | `#FFFFFF` | `#1E2025` | busca/sheet/chips |
| `--text-1` / `--text-2` | `#202124` / `#5F6368` | `#E8EAED` / `#9AA0A6` | textos |
| `--accent` | `#0B57D0` | `#8AB4F8` | UI (nunca no tecido do mapa) |

Serviços/infra (banheiro, locker, coordenação etc.) não ganham preenchimento de área —
ficam idênticos ao chão. Em vez disso, um marcador de ponto (círculo lavanda + "i") sempre
visível em qualquer zoom, seguindo o padrão real de mapa indoor pesquisado originalmente
(Google/Apple tratam serviço como POI pontual, não como área colorida) — essa parte da
proposta original não tinha sido implementada direito na primeira versão; corrigido agora.

## Tipografia

System font stack (`system-ui, -apple-system, "Segoe UI", Roboto`) — offline de verdade e
"nativa do gênero" (SF no iOS, Roboto no Android). Labels de mapa contra-escalados
(tamanho fixo em px de tela, via `--ik = 1/k` — **não cresce com o zoom, de propósito**:
o usuário pediu tamanho legível constante, não crescimento). Halo `paint-order: stroke`
na cor do fundo.

| Nível | Uso | Tamanho (px de tela) |
|---|---|---|
| L1 área | "Praça de Alimentação", "Arena Cultural" | 12px, 600 |
| L2 âncora | patrocinadores (Claro, Itaú…) | 13px, 600 |
| L3 estande | nome da editora | 11px, 500 — só se couber |
| L4 número | código do estande | 9px, 400, tabular |
| UI | busca 16px (evita zoom iOS), sheet título 18px/600 | — |

Os valores da v1 (4.5–9px) eram calibrados para mapa denso tipo metrô, ilegíveis em
celular — subiram todos para a faixa de 9–13px (mínimo confortável em tela de toque).

### "Cabe no estande?" (`fits()` em app/index.html)

Como o rótulo tem tamanho constante em tela mas a caixa do estande cresce com o zoom, a
checagem só pode avaliar o pior caso: o zoom mínimo em que aquele rótulo passa a existir
(limiar do tier Z2 = 3× o zoom de ajuste inicial da tela, `fitBase`). `fits()` recebe esse
`fitBase` e compara a largura estimada do texto contra a largura da caixa nesse zoom
mínimo — não usa mais um multiplicador mágico fixo (a v1 tinha esse bug: nomes vazavam
para estandes vizinhos porque o cálculo não sabia a que zoom real o rótulo apareceria).

## Tiers de zoom (rel = k / k_fit)

- **Z0** rel < 1.6 — perímetro, blocos sem borda individual, só L1 grandes, blue dot.
- **Z1** 1.6–3 — bordas de estande, âncoras L2, áreas pequenas.
- **Z2** 3–5.5 — L3 (se couber) + L4.
- **Z3** ≥ 5.5 — tudo, nomes com quebra em 2 linhas.

Exceção: selecionado/resultado mostra label em qualquer tier. Marcador de serviço/infra e
rótulos de rua/área não seguem os tiers — a rua é geometria visível desde o overview, e o
marcador de serviço precisa ser achável em qualquer zoom (por isso não tem preenchimento
de área concorrendo com ele por atenção).

## UI

Touch targets 48px. Busca: pill flutuante topo, 52px/r26. Chips 36px/r18 roláveis, com
swatch colorido (bolinha) batendo com a cor da categoria no mapa — ensina a associação
cor↔categoria (ativo = amarelo Bienal). FABs 48px canto inferior direito (GPS, grafo).
Bottom sheet r16 topo, handle 32×4. Zoom só pinch/double-tap (sem botões). Dark mode:
`prefers-color-scheme` + toggle persistido.

## Grid do mapa (extração)

Estandes "expositor" são a referência confiável de grid (retângulos limpos do PDF).
Caixas de destaque (patrocinador/entidade/cultural/alimentação/serviço) têm posição e
altura customizadas no PDF original — o mesmo tipo de caixa às vezes é desenhado 1.5x a
altura de uma célula normal, às vezes menos, sem padrão fixo. `tools/build_map.py`
normaliza isso num passo de "encaixe no grid": reposiciona a bbox dessas caixas pra
bordas reais dos estandes/ruas vizinhos (tolerância 20pt em Y, 15pt em X; área ≥ 8000pt²
não encaixa — protege áreas grandes de verdade como Praça/Arena de serem distorcidas) e
sempre reconstrói o `poly` final como retângulo 2D limpo. Fragmentos decorativos finos
(ícones/frestas capturados por engano de cor, sem código nem rótulo, < 8pt no menor lado)
são descartados antes do encaixe.

## Ruas como via de mapa

`tools/build_graph.py` gera `map.json:streets` — não é mais espaço negativo implícito.
Reaproveita a mesma geometria do grafo de corredores: um retângulo por faixa de rua
extraída, uma ponte retangular nos vãos horizontais dentro da mesma fileira (liga faixas
vizinhas), e uma tira vertical de 14pt em cada cruzamento entre fileiras adjacentes
(usando as arestas verticais já calculadas). Renderizado como forma real com
preenchimento + borda (efeito "via de mapa", tipo Google Maps), não só o nome flutuando
sobre o chão genérico.

## Anti-padrões (proibidos)

Gradientes no mapa; sombra em estande (estande é chão, não card); cor de categoria no
tecido de estandes; azul do blue dot como cor de marca/seleção; emoji como ícone de POI
(o marcador de serviço usa um glifo de texto "i", não emoji); todos os nomes em todos os
zooms; radius > ~1px na geometria do mapa (arredondamento generoso é só da UI); silhueta
3D nos destaques (sempre 2D — ver "Grid do mapa" acima).
