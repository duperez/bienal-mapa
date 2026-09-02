import { Map as MlMap, AttributionControl, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// O worker do MapLibre v6 vive num arquivo separado resolvido via
// import.meta.url — no dev do Vite esse caminho não existe no diretório de
// deps otimizados e o mapa trava em silêncio. Servimos a URL via bundler:
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import "./style.css";

setWorkerUrl(maplibreWorkerUrl);

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
    glyphs: `${location.origin}${import.meta.env.BASE_URL}glyphs/{fontstack}/{range}.pbf`,
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

// o container pode medir 0x0 no primeiro paint (webview/painel abrindo);
// garante que o canvas acompanhe o tamanho real assim que ele existir
new ResizeObserver(() => map.resize()).observe(document.getElementById("map")!);

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
  map.fitBounds(VENUE_BOUNDS, { padding: 24, bearing: VENUE_BEARING, animate: false });

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

  map.addLayer({
    id: "ruas",
    type: "fill",
    source: "mapa",
    filter: ["==", ["get", "kind"], "rua"],
    paint: { "fill-color": "#ddd6c8" },
  });
  map.addLayer({
    id: "areas",
    type: "fill",
    source: "mapa",
    filter: ["==", ["get", "kind"], "area"],
    paint: {
      "fill-color": [
        "match", ["get", "cat"],
        "alimentacao", "#ffdca8",
        "cultural", "#b9e0f2",
        "servico", "#e2ded6",
        "infra", "#d5e6d0",
        "#e2ded6",
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
        "alimentacao", "#b36b00",
        "cultural", "#0072a8",
        "#b9b4aa",
      ],
      "line-width": 1,
      "line-opacity": 0.6,
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
  map.addLayer({
    id: "areas-nome",
    type: "symbol",
    source: "mapa",
    filter: ["all", ["==", ["get", "kind"], "area"], ["has", "name"]],
    minzoom: 15.5,
    layout: {
      "text-field": ["get", "name"],
      "text-font": ["Klokantech Noto Sans Bold"],
      "text-size": ["interpolate", ["linear"], ["zoom"], 15.5, 10, 19, 13],
      "text-max-width": 8,
      "text-padding": 6,
    },
    paint: {
      "text-color": [
        "match", ["get", "cat"],
        "alimentacao", "#7a4100",
        "cultural", "#00516e",
        "#474747",
      ],
      "text-halo-color": "#ffffff",
      "text-halo-width": 1.2,
    },
  });

  map.addLayer({
    id: "ruas-nome",
    type: "symbol",
    source: "mapa",
    filter: ["all", ["==", ["get", "kind"], "rua"], ["has", "name"]],
    minzoom: 16,
    layout: {
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
  });

  map.addLayer({
    id: "estandes-nome",
    type: "symbol",
    source: "mapa",
    filter: ["==", ["get", "kind"], "estande"],
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
  });

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
  });
});
