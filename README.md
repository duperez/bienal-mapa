# Mapa Bienal do Livro SP 2026

App pessoal de mapa da 28ª Bienal (Distrito Anhembi, 4–13/09/2026): mapa vetorial
redesenhado a partir do PDF oficial, offline-first, com busca de expositor e (futuro)
rota entre pontos + GPS difuso.

## Estado atual (fase 1 — renderização, SEM rota)

Funcionando, verificado no browser:
- Extração automática do PDF oficial (`reference/mapa-oficial.pdf`, vetorial do Illustrator):
  **244 estandes** com código (A70/AA18/K4/K76 duplicados — ver pendências), **280 nomes**
  no diretório, **48** da Travessa Literária, **54 áreas** (alimentação/cultural/serviço),
  **55 faixas de rua**, grafo de corredores com 70 nós/104 arestas.
- App (`app/index.html`): SVG com pan/zoom/pinch, tiers de zoom (Z0–Z3), busca
  (estandes + áreas + travessa), seleção com bottom sheet, toggle do grafo, light/dark,
  service worker offline (só registra em https). Design system em `docs/design-system.md`.
- Revisado por `reviewer` + `ui-reviewer`; achados relevantes aplicados (tap via pointerup —
  clique real testado —, pan de 2 dedos, SW stale-while-revalidate versionado, busca de áreas,
  labels forçados em seleção/busca).

## Como rodar

```bash
sh tools/build.sh        # PDF -> data/map.json -> app/ (com versão do SW)
python3 -m http.server 8027 -d app     # ou preview "bienal-app" no .claude/launch.json
```

Python: venv em `.venv` com `pymupdf`.

## Pendências (próxima sessão)

1. **Blocos 3D fora do grid** (pedido do Eduardo): patrocinadores/atividades culturais são
   cubos "3D" no PDF e ficaram deslocados — alinhar à fileira vizinha no build (achatar).
2. **GPS não calibrado**: `GEO_REF = null` em `app/index.html`. Polígono real do pavilhão
   (OSM way 203621978, ~322×220m, proporção bate com o hall do mapa 1.47):
   N `-23.5155046,-46.6372162` / NE `-23.5156621,-46.6347654` /
   SE `-23.5176723,-46.6349189` / SW `-23.5174697,-46.6380735`.
   Falta decidir orientação (que lado real = topo do mapa) — Marginal Tietê fica ao SUL do
   prédio; hipótese: entrada pública/Acesso Halls (base do mapa) = lado sul. Confirmar no
   satélite antes de preencher a afim; caso contrário o GPS sai espelhado.
3. **Curadoria de dados** (pós-auditoria de fidelidade de 02/09, 9 regiões vs PDF
   original com 5 agentes): restam apenas — A70 duplicado (o próprio PDF oficial
   imprime 2x, sem candidato claro); B65/K29 no diretório sem estande desenhado no
   original; overlap pontual Chambril D20 x Editora BOC E21; banheiros sem
   classificação própria (ícone genérico de serviço); entradas/portões/setas e
   paredes do pavilhão não viram POIs/geometria.
   [RESOLVIDO 02/09 — auditoria] snap de grid agora valida tamanho/centro antes de
   aplicar (banheiros não são mais esmagados, K24/K26 não se fundem, cluster
   IF14/04/15/16/04A intacto); polígonos em "L" legítimos preservados (IF10, K20);
   códigos quebrados em 2 linhas no PDF fundidos (K40/K42); divisa de estandes
   multi-código no ponto médio real dos rótulos (D80/D70); sub-áreas para códigos
   extras (K18, K20, IF04, IF15, IF16, IF04A); EXT02 desduplicado; typos do mapa
   oficial corrigidos via diretório (AA18→AA20, K76→K74); DD10 Cordel/DD20
   Autógrafos e banheiro do anexo recuperados (filtro de legenda estava largo);
   INDIGO capturada; painéis instagramáveis sintetizados do texto; marcadores
   coloridos de ponta de fileira e calçada externa da Praça renderizados;
   CC26/CC28 na fileira certa (desempate de linha pondera Y).
   [RESOLVIDO 02/09] Travessa Literária extraída (área + 48 mini-lugares TL01–TL48,
   buscáveis); faixa de rua sintética onde o original só tem o texto (RUA H col
   676–783); rótulos com "cabe?" dinâmico por zoom e quebra de linha via CSS
   translate em `em` (o atributo SVG dy="em" resolvia contra 16px no iOS).
4. **Rota (fase 2)**: A* sobre `graph` + snap de origem/destino; grafo ainda precisa de
   ajuste fino (anexo sem verticais, sem ligação hall↔anexo) — ideal via editor visual.
5. **Deploy https** (GitHub Pages ou similar) pra service worker + geolocalização valerem.
6. Achados menores dos reviewers não aplicados: bucketização frágil do diretório (ok pra
   este PDF), `path_points` só 1º retângulo, halo/bordas conferir em aparelho real.
