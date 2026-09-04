/**
 * Gera o ícone do app a partir do próprio mapa.
 *
 * O favicon anterior era o raio genérico do template. Em vez de desenhar um
 * símbolo qualquer, o ícone aqui é derivado do dado: a silhueta real do
 * pavilhão (venue.geojson), as vias que saem do PDF e um traçado em L
 * destacando uma rota. Se o mapa mudar, o ícone muda junto — não vira mais uma
 * peça desenhada à mão para manter em sincronia.
 *
 * Escreve public/favicon.svg, public/icon-192.png e public/icon-512.png. Os
 * PNG existem porque o Chrome no Android ignora ícone SVG no manifest.
 *
 * Uso: node gera-icones.mjs   (só quando o desenho ou a georreferência mudarem)
 */
import { chromium } from "playwright";
import { readFileSync, writeFileSync } from "node:fs";

const url = (p) => new URL(p, import.meta.url);
const ler = (p) => JSON.parse(readFileSync(url(p), "utf8"));

const venue = ler("./public/data/venue.geojson");
const mapa = ler("./public/data/mapa.geojson");

const AMARELO = "#FFD200";
const TINTA = "#101010";
const ROTA = "#1565ff";
const LADO = 512;
const MARGEM = 46;
/** o mapa do app abre girado; o ícone segue o mesmo enquadramento */
const BEARING = 4;

const anel = venue.features[0].geometry.coordinates[0];
const lat0 = anel[0][1];
const kx = Math.cos((lat0 * Math.PI) / 180);
const rad = (BEARING * Math.PI) / 180;

/** lng/lat -> plano local girado pelo bearing, em unidades arbitrárias */
const plano = ([lng, lat]) => {
  const x = (lng - anel[0][0]) * kx;
  const y = lat - anel[0][1];
  return [x * Math.cos(rad) - y * Math.sin(rad), x * Math.sin(rad) + y * Math.cos(rad)];
};

const predio = anel.map(plano);
const xs = predio.map((p) => p[0]);
const ys = predio.map((p) => p[1]);
const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
const escala = (LADO - 2 * MARGEM) / Math.max(x1 - x0, y1 - y0);
const dx = (LADO - (x1 - x0) * escala) / 2;
const dy = (LADO - (y1 - y0) * escala) / 2;

/** plano local -> pixel do ícone (y invertido: no SVG ele cresce para baixo) */
const px = (p) => [(p[0] - x0) * escala + dx, LADO - ((p[1] - y0) * escala + dy)];

const caminho = (pts, fechar) =>
  pts.map((p, i) => `${i ? "L" : "M"}${px(p).map((v) => v.toFixed(1)).join(" ")}`).join("") +
  (fechar ? "Z" : "");

const vias = mapa.features.filter((f) => f.properties?.kind === "via");
const linhas = vias.flatMap((f) =>
  f.geometry.type === "LineString" ? [f.geometry.coordinates] : f.geometry.coordinates,
);

/** o L da rota: a via mais comprida de cada eixo, que é o esqueleto do salão */
const maisLonga = (eixo) =>
  vias
    .filter((f) => f.properties.eixo === eixo && f.geometry.type === "LineString")
    .sort((a, b) => b.properties.extensao_m - a.properties.extensao_m)[0];
const rua = maisLonga("y");
const trav = maisLonga("x");

/** ponta da via `f` mais distante do cruzamento com `outra`, e o cruzamento */
const perna = (f, outra) => {
  const [a, b] = [f.geometry.coordinates[0], f.geometry.coordinates.at(-1)].map(plano);
  const [c, d] = [outra.geometry.coordinates[0], outra.geometry.coordinates.at(-1)].map(plano);
  const p = [(c[0] + d[0]) / 2, (c[1] + d[1]) / 2];
  const t =
    ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) /
    ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2);
  const cruz = [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])];
  const dist = (q) => Math.hypot(q[0] - cruz[0], q[1] - cruz[1]);
  return [dist(a) > dist(b) ? a : b, cruz];
};
const [pontaRua, cruz] = perna(rua, trav);
const [pontaTrav] = perna(trav, rua);

const marca = (p, cor) =>
  `<circle cx="${px(p)[0].toFixed(1)}" cy="${px(p)[1].toFixed(1)}" r="26" fill="${cor}" stroke="${AMARELO}" stroke-width="10"/>`;

const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${LADO} ${LADO}" width="${LADO}" height="${LADO}">
  <rect width="${LADO}" height="${LADO}" rx="96" fill="${AMARELO}"/>
  <path d="${caminho(predio, true)}" fill="${TINTA}" fill-opacity="0.08" stroke="${TINTA}" stroke-width="10" stroke-linejoin="round"/>
  <g fill="none" stroke="${TINTA}" stroke-opacity="0.32" stroke-width="5" stroke-linecap="round">
${linhas.map((l) => `    <path d="${caminho(l.map(plano), false)}"/>`).join("\n")}
  </g>
  <path d="${caminho([pontaRua, cruz, pontaTrav], false)}" fill="none" stroke="${ROTA}" stroke-width="26" stroke-linecap="round" stroke-linejoin="round"/>
  ${marca(pontaRua, ROTA)}
  ${marca(pontaTrav, TINTA)}
</svg>
`;

writeFileSync(url("./public/favicon.svg"), svg);
console.log("favicon.svg");

const navegador = await chromium.launch();
for (const tamanho of [192, 512]) {
  const pagina = await navegador.newPage({
    viewport: { width: tamanho, height: tamanho },
    deviceScaleFactor: 1,
  });
  await pagina.setContent(
    `<html><body style="margin:0">${svg.replace(
      `width="${LADO}" height="${LADO}"`,
      `width="${tamanho}" height="${tamanho}"`,
    )}</body></html>`,
  );
  writeFileSync(url(`./public/icon-${tamanho}.png`), await pagina.screenshot());
  console.log(`icon-${tamanho}.png`);
  await pagina.close();
}
await navegador.close();
