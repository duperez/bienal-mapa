import { Map as MlMap, AttributionControl, setWorkerUrl } from "maplibre-gl";
import { attachSearchUI, buildIndex, subtitle, type Hit } from "./search";
import { addPoiIcons } from "./icons";
import { Rotas, type Malha } from "./rotas";
import { Percurso, type Ponto } from "./percurso";
import { instrucoes, viasDaMalha } from "./instrucoes";
import "maplibre-gl/dist/maplibre-gl.css";
// O worker do MapLibre v6 vive num arquivo separado resolvido via
// import.meta.url — no dev do Vite esse caminho não existe no diretório de
// deps otimizados e o mapa trava em silêncio. Servimos a URL via bundler:
// "?worker&url": o Vite EMPACOTA o worker com as dependências dele e devolve a
// URL do chunk completo. Com "?url" puro, o arquivo é copiado cru e o import
// interno de maplibre-gl-shared.mjs dá 404 no build — worker morre em
// silêncio e nenhuma source processa (mapa "vazio" só em produção).
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "./style.css";

setWorkerUrl(maplibreWorkerUrl);

// erros visíveis: tela muda esconde a causa — qualquer exceção aparece num
// overlay discreto (app pessoal: diagnóstico > estética)
function bboxDe(pts: [number, number][]): [[number, number], [number, number]] {
  let x0 = 180, y0 = 90, x1 = -180, y1 = -90;
  for (const [x, y] of pts) {
    if (x < x0) x0 = x;
    if (y < y0) y0 = y;
    if (x > x1) x1 = x;
    if (y > y1) y1 = y;
  }
  return [[x0, y0], [x1, y1]];
}

function showError(msg: string): void {
  let el = document.getElementById("errOverlay");
  if (!el) {
    el = document.createElement("div");
    el.id = "errOverlay";
    document.body.appendChild(el);
  }
  el.textContent = msg;
}
window.addEventListener("error", (e) => showError(`Erro: ${e.message}`));
window.addEventListener("unhandledrejection", (e) =>
  showError(`Erro: ${e.reason?.message ?? e.reason}`),
);

// Service worker: é ele que faz o app abrir dentro do pavilhão, onde o wifi
// do evento não vence a multidão e o 4G não atravessa a laje. Sem isso, o
// projeto inteiro depende de uma rede que a gente sabe que não vai ter.
//
// Só no build: em dev o SW serviria a versão em cache e esconderia a edição.
// O arquivo é gerado por vite.config.ts com a lista real do bundle.
if ("serviceWorker" in navigator) {
  if (import.meta.env.PROD) {
    addEventListener("load", () => {
      // BASE_URL e não import.meta.url: o bundle mora em assets/, e registrar
      // relativo a ele deixaria o escopo do SW preso em /assets/
      navigator.serviceWorker.register(`${import.meta.env.BASE_URL}sw.js`).catch(() => {});
    });
  } else {
    // a origem :8027 já serviu o app legado com SW cache-first; em dev,
    // qualquer registro residual (dele ou do build) intercepta os requests
    navigator.serviceWorker
      .getRegistrations()
      .then((rs) => rs.forEach((r) => r.unregister()))
      .catch(() => {});
  }
}

/**
 * Marco 1 do app novo: MapLibre rodando 100% local (nenhum tile/fonte externo),
 * com o pavilhão real do Anhembi georreferenciado (OSM way 203621978) como
 * primeira camada. As camadas do mapa da Bienal entram por cima nas próximas
 * etapas, geradas de data/structure.json.
 */

/** Contorno do pavilhão (lng/lat). Carregado do GeoJSON versionado. */
const VENUE_URL = `${import.meta.env.BASE_URL}data/venue.geojson`;

/** Centro e rotação: o prédio é ~4° torto em relação ao norte; giramos a
 * câmera para o pavilhão aparecer "endireitado", como apps de arena fazem. */
// Enquadrar pelo polígono do prédio deixava um terço da tela vazio: o desenho
// oficial não cobre o Distrito Anhembi inteiro. O bbox abaixo é só o palpite
// inicial — assim que o mapa.geojson chega, `frameVenue` reenquadra pelo bbox
// real dos dados, para a constante nunca mais envelhecer junto com a escala.
let VENUE_BOUNDS: [[number, number], [number, number]] = [
  [-46.63802, -23.51712],
  [-46.6348, -23.515476],
];
// azimute do lado norte do prédio ≈ 94° (leste, 4° pro sul); para ele ficar
// horizontal na tela o topo do mapa aponta pra 94−90 = +4°
const VENUE_BEARING = 4;

const map = new MlMap({
  container: "map",
  // estilo 100% local: fundo neutro, glyphs de fonte servidos pelo próprio app
  style: {
    version: 8,
    // URL absoluta resolvida da base (funciona na raiz e em subcaminho/Pages)
    glyphs: `${new URL(import.meta.env.BASE_URL, location.href).href}glyphs/{fontstack}/{range}.pbf`,
    sources: {},
    layers: [
      { id: "background", type: "background", paint: { "background-color": "#e4e1db" } },
    ],
  },
  bounds: VENUE_BOUNDS,
  fitBoundsOptions: { padding: 24 },
  bearing: VENUE_BEARING,
  maxBounds: [
    [-46.6455, -23.5225],
    [-46.6275, -23.5105],
  ],
  minZoom: 14,
  maxZoom: 22,
  // nosso bearing fixo é +4°, dentro da zona default de "snap para o norte"
  // (7°) — sem isso, todo fim de gesto gira o mapa de volta pro torto
  bearingSnap: 0,
  attributionControl: false,
});

map.addControl(
  new AttributionControl({ compact: true, customAttribution: "© OpenStreetMap (ODbL)" }),
  "bottom-right",
);

// mapa de pavilhão: rotação e inclinação livres só desorientam — travadas.
// O bearing fixo "endireita" o prédio (ele é ~4° torto em relação ao norte).
map.dragRotate.disable();
map.touchZoomRotate.disableRotation();
map.touchPitch.disable();
map.keyboard.disableRotation();

// Enquadramento inicial robusto: fitBounds com container 0x0 manda a câmera
// pra zoom máximo num ponto qualquer (tela "vazia"). Só enquadra com medida
// válida — e se o load rodou cedo demais, o primeiro resize real reenquadra.
let cameraSet = false;
function frameVenue(): void {
  const el = document.getElementById("map")!;
  if (!el.clientWidth || !el.clientHeight) return;
  map.fitBounds(VENUE_BOUNDS, { padding: 24, bearing: VENUE_BEARING, animate: false });
  cameraSet = true;
}

// o container pode medir 0x0 no primeiro paint (webview/painel abrindo);
// garante que o canvas acompanhe o tamanho real assim que ele existir
new ResizeObserver(() => {
  map.resize();
  if (!cameraSet) frameVenue();
}).observe(document.getElementById("map")!);

// acesso de debug no console (sem efeito em produção)
declare global {
  interface Window {
    __map?: MlMap;
  }
}
window.__map = map;

const MAPA_URL = `${import.meta.env.BASE_URL}data/mapa.geojson`;
const MALHA_URL = `${import.meta.env.BASE_URL}data/malha.json`;

map.on("load", async () => {
  // o `bounds` do construtor aplica a câmera com bearing 0 (reset assíncrono);
  // reenquadra com o bearing que endireita o prédio, sem animação
  frameVenue();

  const [venue, mapa, malha] = await Promise.all([
    fetch(VENUE_URL).then((r) => r.json()),
    fetch(MAPA_URL).then((r) => r.json()),
    fetch(MALHA_URL).then((r) => r.json()),
  ]);
  const rotas = new Rotas(malha as Malha);

  map.addSource("venue", { type: "geojson", data: venue });
  map.addLayer({
    id: "venue-fill",
    type: "fill",
    source: "venue",
    paint: { "fill-color": "#edebe7" },
  });
  map.addLayer({
    id: "venue-outline",
    type: "line",
    source: "venue",
    paint: { "line-color": "#9b968c", "line-width": 2 },
  });

  map.addSource("mapa", { type: "geojson", data: mapa });

  // bbox real do que foi transcrito -> reenquadra. Feito depois do fetch e
  // antes das camadas, para o primeiro frame já sair no lugar certo.
  let x0 = 180, y0 = 90, x1 = -180, y1 = -90;
  const varre = (c: unknown): void => {
    if (typeof (c as number[])[0] === "number") {
      const [x, y] = c as number[];
      if (x < x0) x0 = x;
      if (y < y0) y0 = y;
      if (x > x1) x1 = x;
      if (y > y1) y1 = y;
    } else for (const f of c as unknown[]) varre(f);
  };
  for (const f of mapa.features) varre(f.geometry.coordinates);
  if (x0 < x1 && y0 < y1) {
    VENUE_BOUNDS = [[x0, y0], [x1, y1]];
    cameraSet = false;
    frameVenue();
  }

  // piso da tenda do anexo (mesma linguagem visual do prédio)
  map.addLayer({
    id: "piso",
    type: "fill",
    source: "mapa",
    filter: ["==", ["get", "kind"], "piso"],
    paint: { "fill-color": "#edebe7" },
  });
  map.addLayer({
    id: "piso-borda",
    type: "line",
    source: "mapa",
    filter: ["==", ["get", "kind"], "piso"],
    paint: { "line-color": "#9b968c", "line-width": 1.5 },
  });

  map.addLayer({
    id: "circulacao",
    type: "fill",
    source: "mapa",
    filter: ["==", ["get", "kind"], "circulacao"],
    paint: { "fill-color": "#f4f1ea" },
  });
  // as vias derivadas viram fita clara: o corredor lê como rua, não como sobra
  map.addLayer({
    id: "vias",
    type: "line",
    source: "mapa",
    filter: ["==", ["get", "kind"], "via"],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": "#ffffff",
      "line-opacity": 0.75,
      "line-width": ["interpolate", ["exponential", 2], ["zoom"],
        15, ["*", ["get", "largura_m"], 0.06],
        20, ["*", ["get", "largura_m"], 2.0]],
    },
  });

  // as setas do PDF não são mais desenhadas: viraram as vias acima. Ficam no
  // dado como procedência do nome, não como pintura.
  // chão quieto: fills suaves — a cor forte fica no pin/rótulo (padrão GMaps)
  map.addLayer({
    id: "areas",
    type: "fill",
    source: "mapa",
    filter: ["==", ["get", "kind"], "area"],
    paint: {
      "fill-color": [
        "match", ["get", "cat"],
        "alimentacao", "#ffe8c4",
        "cultural", "#d5eaf4",
        "servico", "#e6e2da",
        "infra", "#ddead8",
        "#e6e2da",
      ],
    },
  });
  map.addLayer({
    id: "areas-borda",
    type: "line",
    source: "mapa",
    filter: ["==", ["get", "kind"], "area"],
    paint: {
      "line-color": [
        "match", ["get", "cat"],
        "alimentacao", "#d9a253",
        "cultural", "#7db8d4",
        "#c5c0b6",
      ],
      "line-width": 1,
      "line-opacity": 0.5,
    },
  });
  map.addLayer({
    id: "quadras",
    type: "line",
    source: "mapa",
    filter: ["==", ["get", "kind"], "quadra"],
    paint: { "line-color": "#b9b4aa", "line-width": 1.2 },
  });
  map.addLayer({
    id: "estandes",
    type: "fill",
    source: "mapa",
    filter: ["==", ["get", "kind"], "estande"],
    paint: {
      // expositor fica branco (chão quieto); as categorias da legenda oficial
      // ganham um tom suave — cor com função, não decoração
      "fill-color": [
        "match", ["get", "cat"],
        "patrocinador", "#fff6c9",
        "entidade", "#efe4f4",
        "travessa", "#f5f1e8",
        "#ffffff",
      ],
    },
  });
  map.addLayer({
    id: "estandes-borda",
    type: "line",
    source: "mapa",
    filter: ["==", ["get", "kind"], "estande"],
    paint: {
      "line-color": [
        "match", ["get", "cat"],
        "patrocinador", "#d9b93a",
        "entidade", "#a98bbd",
        "#d3cfc7",
      ],
      // borda hairline que só engrossa de leve com o zoom
      "line-width": ["interpolate", ["linear"], ["zoom"], 16, 0.4, 20, 1.2],
    },
  });

  // ---- rótulos: colisão e densidade por zoom são do motor ----
  addPoiIcons(map);

  // áreas como POI: pin circular colorido + nome (linguagem do Google Maps).
  // Serviço sem nome = banheiro (pin WC, só ícone).
  map.addLayer({
    id: "areas-poi",
    type: "symbol",
    source: "mapa",
    filter: [
      "all",
      ["==", ["get", "kind"], "area"],
      ["has", "name"],
      ["!=", ["get", "cat"], "servico"],
      ["!=", ["get", "cat"], "infra"],
    ],
    minzoom: 15.6,
    layout: {
      "icon-image": [
        "case",
        ["!", ["has", "name"]],
        "poi-wc",
        [
          "match", ["get", "cat"],
          "alimentacao", "poi-alimentacao",
          "cultural", "poi-cultural",
          "poi-servico",
        ],
      ],
      "icon-size": ["interpolate", ["linear"], ["zoom"], 15.6, 0.72, 18, 1],
      "text-field": ["get", "name"],
      "text-font": ["Klokantech Noto Sans Bold"],
      "text-size": ["interpolate", ["linear"], ["zoom"], 15.6, 10, 19, 12.5],
      "text-max-width": 8,
      "text-padding": 4,
      "text-anchor": "top",
      "text-offset": [0, 1.05],
      "text-optional": false,
      // área maior ganha a disputa por espaço de rótulo
      "symbol-sort-key": ["-", 0, ["coalesce", ["get", "peso"], 0]],
    },
    paint: {
      "text-color": [
        "match", ["get", "cat"],
        "alimentacao", "#8a5200",
        "cultural", "#0a628a",
        "#5a564e",
      ],
      "text-halo-color": "#ffffff",
      "text-halo-width": 1.3,
    },
  });

  // serviços e banheiros: pins entram um passo de zoom depois (densidade GMaps)
  map.addLayer({
    id: "areas-poi-servico",
    type: "symbol",
    source: "mapa",
    filter: [
      "all",
      ["==", ["get", "kind"], "area"],
      ["any", ["==", ["get", "cat"], "servico"], ["==", ["get", "cat"], "infra"]],
      ["any", ["has", "name"], ["==", ["get", "cat"], "servico"]],
    ],
    minzoom: 16.8,
    layout: {
      "icon-image": ["case", ["!", ["has", "name"]], "poi-wc", "poi-servico"],
      "icon-size": ["interpolate", ["linear"], ["zoom"], 16.8, 0.78, 18.5, 1],
      "text-field": ["get", "name"],
      "text-font": ["Klokantech Noto Sans Bold"],
      "text-size": 11.5,
      "text-max-width": 8,
      "text-padding": 4,
      "text-anchor": "top",
      "text-offset": [0, 1.05],
      "text-optional": false,
    },
    paint: {
      "text-color": "#5a564e",
      "text-halo-color": "#ffffff",
      "text-halo-width": 1.3,
    },
  }, "areas-poi");

  // entradas: os POIs mais importantes de um mapa de evento
  map.addLayer({
    id: "pois-entrada",
    type: "symbol",
    source: "mapa",
    filter: ["==", ["get", "kind"], "poi"],
    minzoom: 15,
    layout: {
      "icon-image": [
        "match", ["get", "cat"],
        "saida", "poi-saida",
        "escolas", "poi-cultural",
        "poi-entrada",
      ],
      "icon-size": ["interpolate", ["linear"], ["zoom"], 15, 0.72, 18, 1],
      "text-field": ["get", "name"],
      "text-font": ["Klokantech Noto Sans Bold"],
      "text-size": 11.5,
      "text-max-width": 7,
      "text-anchor": "top",
      "text-offset": [0, 1.05],
      "text-optional": false,
      "symbol-sort-key": -99999,
    },
    paint: {
      "text-color": ["case", ["==", ["get", "cat"], "saida"], "#8f2a20", "#186439"],
      "text-halo-color": "#ffffff",
      "text-halo-width": 1.3,
    },
  });

  // nome da rua corre AO LONGO da via, repetindo
  map.addLayer({
    id: "ruas-nome",
    type: "symbol",
    source: "mapa",
    filter: ["==", ["get", "kind"], "via"],
    minzoom: 16,
    layout: {
      "symbol-placement": "line",
      "symbol-spacing": 320,
      "text-field": ["get", "name"],
      "text-font": ["Klokantech Noto Sans Regular"],
      "text-size": 11,
      "text-letter-spacing": 0.15,
    },
    paint: {
      "text-color": "#8a857b",
      "text-halo-color": "#ffffff",
      "text-halo-width": 1.4,
    },
  }, "areas-poi");

  map.addLayer({
    id: "estandes-nome",
    type: "symbol",
    source: "mapa",
    filter: ["all", ["==", ["get", "kind"], "estande"], ["!=", ["get", "mini"], true]],
    minzoom: 17.5,
    layout: {
      "text-field": ["coalesce", ["get", "name"], ["get", "code"]],
      "text-font": ["Klokantech Noto Sans Regular"],
      "text-size": ["interpolate", ["linear"], ["zoom"], 17.5, 10, 20, 14],
      "text-max-width": 7,
      "text-padding": 4,
    },
    paint: {
      "text-color": "#202124",
      "text-halo-color": "#ffffff",
      "text-halo-width": 1.4,
    },
  }, "areas-poi");

  // destaque de seleção: source dedicada, atualizada ao selecionar
  map.addSource("sel", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  map.addLayer(
    {
      id: "sel-fill",
      type: "fill",
      source: "sel",
      paint: { "fill-color": "#ffd200", "fill-opacity": 0.85 },
    },
    "areas-poi",
  );
  map.addLayer(
    {
      id: "sel-borda",
      type: "line",
      source: "sel",
      paint: { "line-color": "#8a7000", "line-width": 2 },
    },
    "areas-poi",
  );

  // cabines minúsculas (Travessa/Alameda/fileira AA): nome só bem de perto
  map.addLayer({
    id: "estandes-nome-mini",
    type: "symbol",
    source: "mapa",
    filter: ["all", ["==", ["get", "kind"], "estande"], ["==", ["get", "mini"], true]],
    minzoom: 19.6,
    layout: {
      "text-field": ["coalesce", ["get", "name"], ["get", "code"]],
      "text-font": ["Klokantech Noto Sans Regular"],
      "text-size": 10,
      "text-max-width": 6,
      "text-padding": 2,
    },
    paint: {
      "text-color": "#202124",
      "text-halo-color": "#ffffff",
      "text-halo-width": 1.4,
    },
  }, "areas-poi");

  map.addLayer({
    id: "estandes-codigo",
    type: "symbol",
    source: "mapa",
    filter: ["all", ["==", ["get", "kind"], "estande"], ["has", "name"]],
    minzoom: 19,
    layout: {
      "text-field": ["get", "code"],
      "text-font": ["Klokantech Noto Sans Regular"],
      "text-size": 9,
      "text-offset": [0, 1.6],
      "text-anchor": "top",
      "text-padding": 2,
    },
    paint: {
      "text-color": "#5f6368",
      "text-halo-color": "#ffffff",
      "text-halo-width": 1.2,
    },
  }, "areas-poi");

  // ---- rota ----
  // desenhada acima de tudo: é resposta a uma pergunta do visitante, não
  // contexto. Duas linhas, uma mais grossa por baixo, para o traço se destacar
  // tanto do piso claro quanto dos blocos.
  map.addSource("rota", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  map.addLayer({
    id: "rota-halo",
    type: "line",
    source: "rota",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#ffffff", "line-width": 9, "line-opacity": 0.9 },
  });
  map.addLayer({
    id: "rota-linha",
    type: "line",
    source: "rota",
    layout: { "line-cap": "round", "line-join": "round" },
    // trechos alternam entre dois azuis: com paradas, um traço de cor única
    // vira um emaranhado onde não se enxerga onde um pedaço acaba
    paint: {
      "line-color": ["case", ["==", ["%", ["get", "trecho"], 2], 0], "#1a73e8", "#5b9bf5"],
      "line-width": 5,
    },
  });
  // setas ao longo do traçado: sem elas a ordem das paradas só existe na
  // lista, e o visitante tem que voltar a ler para saber para que lado ir
  map.addLayer({
    id: "rota-seta",
    type: "symbol",
    source: "rota",
    layout: {
      "symbol-placement": "line",
      "symbol-spacing": 60,
      "text-field": "▶",
      "text-font": ["Klokantech Noto Sans Bold"],
      "text-size": 11,
      "text-keep-upright": false,
      "text-allow-overlap": true,
    },
    paint: { "text-color": "#ffffff", "text-halo-color": "#1a73e8", "text-halo-width": 1 },
  });

  const setRota = (features: GeoJSON.Feature[]) =>
    (map.getSource("rota") as import("maplibre-gl").GeoJSONSource).setData({
      type: "FeatureCollection",
      features,
    });

  // ---- marcadores das paradas ----
  map.addSource("pontos", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  map.addLayer({
    id: "pontos-circulo",
    type: "circle",
    source: "pontos",
    paint: {
      "circle-radius": 11,
      "circle-color": [
        "match",
        ["get", "papel"],
        "origem", "#1a73e8",
        "destino", "#d93025",
        "#f29900",
      ],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 2.5,
    },
  });
  map.addLayer({
    id: "pontos-letra",
    type: "symbol",
    source: "pontos",
    layout: {
      "text-field": ["get", "letra"],
      "text-font": ["Klokantech Noto Sans Bold"],
      "text-size": 12,
      "text-allow-overlap": true,
    },
    paint: { "text-color": "#ffffff" },
  });

  const setPontos = (features: GeoJSON.Feature[]) =>
    (map.getSource("pontos") as import("maplibre-gl").GeoJSONSource).setData({
      type: "FeatureCollection",
      features,
    });

  // ---- busca + seleção ----
  const setSel = (features: GeoJSON.Feature[]) =>
    (map.getSource("sel") as import("maplibre-gl").GeoJSONSource).setData({
      type: "FeatureCollection",
      features,
    });

  const sheet = document.createElement("div");
  sheet.id = "sheet";
  sheet.innerHTML =
    `<div class="handle"></div><div id="sheetTitle"></div><div id="sheetSub"></div>` +
    `<button id="sheetRota" type="button">Como chegar</button>`;
  document.body.appendChild(sheet);

  const btnRota = document.getElementById("sheetRota") as HTMLButtonElement;

  function openSheet(title: string, sub: string): void {
    (document.getElementById("sheetTitle") as HTMLElement).textContent = title;
    (document.getElementById("sheetSub") as HTMLElement).textContent = sub;
    sheet.classList.add("open");
    // as duas gavetas dividem a borda de baixo: a ficha manda enquanto está
    // aberta e o percurso recolhe, senão o botão dela fica sob o painel
    document.body.classList.add("ficha");
  }
  function closeSheet(): void {
    sheet.classList.remove("open");
    document.body.classList.remove("ficha");
    setSel([]);
    // o traçado NÃO some junto: a ficha é sobre um lugar, o percurso é sobre
    // o trajeto. Fechar a ficha para enxergar o mapa é o gesto natural de
    // quem está seguindo a rota.
    if (!percurso.aberto) setRota([]);
  }
  // o clique no botão não pode fechar a ficha junto
  sheet.addEventListener("click", (e) => {
    if (e.target !== btnRota) closeSheet();
  });

  // ---- percurso com paradas ----
  const pontoDe = (h: Hit): Ponto | null => {
    const cel = rotas.acesso(h.code ?? h.name);
    return cel ? { rotulo: h.name, cel } : null;
  };

  const index = buildIndex(mapa);
  // as vias saem do PDF e viram régua das instruções; convertidas uma vez só
  const vias = viasDaMalha(mapa, rotas);

  const percurso = new Percurso({
    rotas,
    // um traço por trecho, e não um traço só emendado: com paradas o visitante
    // precisa enxergar onde um pedaço acaba e o outro começa
    desenhaRota: (trechos) =>
      setRota(
        trechos.map((cels, i) => ({
          type: "Feature",
          properties: { trecho: i },
          geometry: { type: "LineString", coordinates: cels.map((c) => rotas.lngLat(c)) },
        })),
      ),
    desenhaPontos: (paradas) =>
      setPontos(
        paradas
          .map((p, i) => ({ p, i }))
          .filter(({ p }) => p)
          .map(({ p, i }) => ({
            type: "Feature",
            properties: {
              papel: i === 0 ? "origem" : i === paradas.length - 1 ? "destino" : "parada",
              letra: String.fromCharCode(65 + (i % 26)),
            },
            geometry: { type: "Point", coordinates: rotas.lngLat(p!.cel) },
          })),
      ),
    enquadra: (cels) =>
      map.fitBounds(bboxDe(cels.map((c) => rotas.lngLat(c))), {
        padding: { top: 90, bottom: 300, left: 40, right: 40 },
        bearing: VENUE_BEARING,
        duration: 700,
      }),
    instrucoes: (cels, destino) => instrucoes(cels, vias, rotas, destino),
    aoEscolher: (i) => {
      document.body.classList.toggle("escolhendo", i !== null);
      if (i !== null) closeSheet();
    },
  });

  let alvoRota: Hit | null = null;
  btnRota.addEventListener("click", () => {
    if (!alvoRota) return;
    const p = pontoDe(alvoRota);
    if (!p) {
      (document.getElementById("sheetSub") as HTMLElement).textContent =
        "sem ponto de acesso na malha";
      return;
    }
    sheet.classList.remove("open");
    document.body.classList.remove("ficha");
    setSel([]);
    percurso.abrir(p);
  });

  function pick(h: Hit, fly: boolean): void {
    // em modo de escolha, tocar num lugar preenche o campo em vez de abrir
    // a ficha — é o mesmo gesto do fluxo normal, com outro destino
    if (percurso.escolhendo !== null) {
      const p = pontoDe(h);
      if (p) {
        percurso.define(p);
        return;
      }
    }
    setSel([h.feature]);
    if (!percurso.aberto) setRota([]);
    alvoRota = h;
    btnRota.hidden = !pontoDe(h);
    // com percurso montado, o gesto natural do visitante é "e depois quero ir
    // ali também" — o mesmo botão passa a acrescentar em vez de recomeçar
    btnRota.textContent =
      percurso.aberto && percurso.preenchidas >= 2 ? "Adicionar ao percurso" : "Como chegar";
    openSheet(h.name, subtitle(h));
    if (fly) {
      map.flyTo({
        center: h.center,
        zoom: h.kind === "area" ? 17.8 : 19.4,
        bearing: VENUE_BEARING,
        duration: 900,
        // sheet cobre a base da tela: puxa o alvo um pouco pra cima
        offset: [0, -40],
      });
    }
  }

  attachSearchUI(index, (h) => pick(h, true));

  // tap num estande/área do mapa abre a ficha (sem voo)
  const indexByKey = new Map(index.map((h) => [`${h.kind}:${h.code ?? h.name}`, h]));
  for (const layerId of ["estandes", "areas"]) {
    map.on("click", layerId, (e) => {
      const f = e.features?.[0];
      if (!f) return;
      const p = f.properties ?? {};
      const h = indexByKey.get(`${p.kind}:${p.code ?? p.name}`);
      if (h) {
        pick(h, false);
        e.preventDefault();
      }
    });
    map.on("mouseenter", layerId, () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", layerId, () => (map.getCanvas().style.cursor = ""));
  }
  map.on("click", (e) => {
    if (e.defaultPrevented) return;
    // toque em área livre durante a escolha vira ponto do percurso, com snap
    // para a célula caminhável mais próxima: dedo em tela de celular erra o
    // corredor com facilidade, e ponto em cima de estande não gera rota
    if (percurso.escolhendo !== null) {
      const cel = rotas.maisProximaLivre(e.lngLat.lng, e.lngLat.lat, 25);
      if (cel) percurso.define({ rotulo: "Ponto no mapa", cel });
      return;
    }
    closeSheet();
  });
});
