import { Map as MlMap, AttributionControl, setWorkerUrl } from "maplibre-gl";
import { attachSearchUI, buildIndex, subtitle, type Hit } from "./search";
import { addPoiIcons } from "./icons";
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

// a origem :8027 já serviu o app legado com service worker cache-first;
// qualquer SW residual dessa era intercepta os requests — remove todos
// (o app novo ganhará SW próprio via vite-plugin-pwa em outra rodada)
if ("serviceWorker" in navigator) {
  navigator.serviceWorker
    .getRegistrations()
    .then((rs) => rs.forEach((r) => r.unregister()))
    .catch(() => {});
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
const VENUE_BOUNDS: [[number, number], [number, number]] = [
  [-46.6385, -23.5181],
  [-46.6343, -23.5151],
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

map.on("load", async () => {
  // o `bounds` do construtor aplica a câmera com bearing 0 (reset assíncrono);
  // reenquadra com o bearing que endireita o prédio, sem animação
  frameVenue();

  const [venue, mapa] = await Promise.all([
    fetch(VENUE_URL).then((r) => r.json()),
    fetch(MAPA_URL).then((r) => r.json()),
  ]);

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
    id: "ruas",
    type: "fill",
    source: "mapa",
    filter: ["==", ["get", "kind"], "rua"],
    paint: { "fill-color": "#ddd6c8" },
  });
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
    paint: { "fill-color": "#ffffff" },
  });
  map.addLayer({
    id: "estandes-borda",
    type: "line",
    source: "mapa",
    filter: ["==", ["get", "kind"], "estande"],
    paint: {
      "line-color": "#d3cfc7",
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
      "icon-image": ["case", ["==", ["get", "cat"], "saida"], "poi-saida", "poi-entrada"],
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
    filter: ["==", ["get", "kind"], "rua-eixo"],
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
      "text-halo-color": "#ddd6c8",
      "text-halo-width": 1.2,
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

  // ---- busca + seleção ----
  const setSel = (features: GeoJSON.Feature[]) =>
    (map.getSource("sel") as import("maplibre-gl").GeoJSONSource).setData({
      type: "FeatureCollection",
      features,
    });

  const sheet = document.createElement("div");
  sheet.id = "sheet";
  sheet.innerHTML = `<div class="handle"></div><div id="sheetTitle"></div><div id="sheetSub"></div>`;
  document.body.appendChild(sheet);

  function openSheet(title: string, sub: string): void {
    (document.getElementById("sheetTitle") as HTMLElement).textContent = title;
    (document.getElementById("sheetSub") as HTMLElement).textContent = sub;
    sheet.classList.add("open");
  }
  function closeSheet(): void {
    sheet.classList.remove("open");
    setSel([]);
  }
  sheet.addEventListener("click", closeSheet);

  function pick(h: Hit, fly: boolean): void {
    setSel([h.feature]);
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

  const index = buildIndex(mapa);
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
    if (!e.defaultPrevented) closeSheet();
  });
});
