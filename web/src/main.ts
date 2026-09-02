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
const VENUE_BEARING = -4;

const map = new MlMap({
  container: "map",
  // estilo 100% local: fundo neutro; sem fontes/tiles remotos (offline-first)
  style: {
    version: 8,
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
  attributionControl: false,
});

map.addControl(
  new AttributionControl({ compact: true, customAttribution: "© OpenStreetMap (ODbL)" }),
  "bottom-right",
);

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

map.on("load", async () => {
  const venue = await fetch(VENUE_URL).then((r) => r.json());

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
});
