/**
 * Teste da câmera: girar o mapa com o dedo.
 *
 * O visitante está de pé no pavilhão olhando para uma direção física, e girar o
 * mapa até bater é o único jeito de casar os dois — a bússola do aparelho não
 * serve, porque o telhado é metálico e distorce o magnetômetro.
 *
 * O gesto em si é uma linha de código. O que precisa de teste é o que vem
 * depois: o app reimpunha `bearing: VENUE_BEARING` em todo `flyTo` e todo
 * `fitBounds`, então bastava tocar num estande para desfazer o alinhamento que
 * a pessoa tinha acabado de fazer. Esse defeito não aparece em nenhuma tela
 * parada — só quando se gira e depois se usa o app normalmente.
 *
 * Uso: node test-mapa.mjs   (opcional: porta, padrão 5173)
 */
import { chromium } from "playwright";

const porta = process.argv[2] || "5173";
const falhas = [];
const checa = (nome, ok, detalhe = "") => {
  if (ok) console.log(`ok   ${nome}${detalhe ? ` (${detalhe})` : ""}`);
  else {
    console.log(`FALHOU: ${nome}${detalhe ? ` (${detalhe})` : ""}`);
    falhas.push(nome);
  }
};

/** o ângulo do prédio endireitado; o mapa "reto" nunca é o norte geográfico */
const RETO = 4;

const navegador = await chromium.launch();
const pagina = await navegador.newPage({ viewport: { width: 900, height: 800 } });
const errosDePagina = [];
pagina.on("pageerror", (e) => errosDePagina.push(String(e)));
await pagina.goto(`http://localhost:${porta}/`, { waitUntil: "networkidle" });
await pagina.waitForFunction(() => window.__map?.isStyleLoaded?.());
await pagina.waitForTimeout(1200);

const girar = (graus) =>
  pagina.evaluate(
    (g) =>
      new Promise((pronto) => {
        window.__map.once("moveend", () => setTimeout(pronto, 350));
        window.__map.setBearing(g);
        window.__map.fire("rotatestart", { originalEvent: new Event("touchstart") });
        window.__map.fire("rotate");
        window.__map.fire("rotateend");
      }),
    graus,
  );
const bearing = () => pagina.evaluate(() => Math.round(window.__map.getBearing() * 10) / 10);
const bussolaVisivel = () => pagina.locator("#bussola").isVisible();

// ---- o gesto está liberado ----
const gestos = await pagina.evaluate(() => ({
  arrasta: window.__map.dragRotate.isEnabled(),
  toque: window.__map.touchZoomRotate.isEnabled(),
  // planta baixa em perspectiva só esconde o fundo da tela
  inclina: window.__map.touchPitch.isEnabled(),
}));
checa("arrastar gira o mapa", gestos.arrasta);
checa("dois dedos giram o mapa", gestos.toque);
checa("inclinação continua travada", !gestos.inclina);

// ---- a bússola só existe quando faz falta ----
checa("mapa começa endireitado", Math.abs((await bearing()) - RETO) < 0.5, `${await bearing()}°`);
checa("sem bússola com o prédio no lugar", !(await bussolaVisivel()));

await girar(75);
checa("bússola aparece com o mapa torto", await bussolaVisivel());

// a agulha aponta para o "cima do prédio", ou seja, desgira o quanto o mapa
// girou — se ela girasse junto, apontaria para o mesmo lado em todo ângulo
const giroAgulha = await pagina.evaluate(() =>
  getComputedStyle(document.querySelector("#bussola svg")).transform,
);
checa("a agulha desgira junto com o mapa", giroAgulha !== "none" && giroAgulha !== "matrix(1, 0, 0, 1, 0, 0)", giroAgulha);

// ---- o giro sobrevive ao uso normal do app ----
// este é o defeito de verdade: enquadrar não é motivo para reorientar
await pagina.fill("#searchInput", "Rocco");
await pagina.waitForTimeout(500);
await pagina.click("#searchResults > *:first-child");
await pagina.waitForTimeout(1500);
const depoisDaBusca = await bearing();
checa("tocar num estande não desfaz o giro", Math.abs(depoisDaBusca - 75) < 1, `${depoisDaBusca}°`);

await pagina.click("#sheetRota");
await pagina.waitForTimeout(500);
await pagina.fill("#searchInput", "Espaço Educação");
await pagina.waitForTimeout(500);
await pagina.click("#searchResults > *:first-child");
await pagina.waitForTimeout(400);
await pagina.click("#sheetRota");
await pagina.waitForTimeout(1600);
const depoisDaRota = await bearing();
checa("enquadrar a rota não desfaz o giro", Math.abs(depoisDaRota - 75) < 1, `${depoisDaRota}°`);

// as setas da rota são texto em linha; sem keep-upright falso o MapLibre as
// virava de cabeça para baixo para "ficarem legíveis" e a seta apontaria para
// trás — erro que só existe depois que o mapa pode girar
const seta = await pagina.evaluate(() =>
  window.__map.getLayoutProperty("rota-seta", "text-keep-upright"),
);
checa("seta da rota não inverte ao girar", seta === false, String(seta));

// ---- o caminho de volta ----
await pagina.click("#bussola");
await pagina.waitForTimeout(700);
const voltou = await bearing();
checa("bússola endireita o prédio", Math.abs(voltou - RETO) < 0.5, `${voltou}°`);
checa("bússola some depois de endireitar", !(await bussolaVisivel()));

// encaixe: quase reto vira reto, senão não há como fechar o alinhamento a dedo
await girar(RETO + 4);
await pagina.waitForTimeout(600);
const encaixou = await bearing();
checa("quase reto encaixa no reto", Math.abs(encaixou - RETO) < 0.5, `${encaixou}°`);

await girar(RETO + 25);
await pagina.waitForTimeout(600);
const livre = await bearing();
checa("longe do reto não é puxado", Math.abs(livre - (RETO + 25)) < 1, `${livre}°`);

checa("nenhum erro de página", errosDePagina.length === 0, errosDePagina[0] || "");

await navegador.close();
console.log(falhas.length ? `\n${falhas.length} falha(s)` : "\ntudo certo");
process.exit(falhas.length ? 1 : 0);
