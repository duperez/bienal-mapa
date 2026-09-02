// Screenshots de análise: várias vistas do mapa renderizado de verdade.
import { chromium } from "playwright";

const vistas = [
  { nome: "overview", zoom: 16.4, center: [-46.6364, -23.5166] },
  { nome: "miolo-medio", zoom: 18.2, center: [-46.6372, -23.5163] },
  { nome: "nordeste", zoom: 18.0, center: [-46.6355, -23.5159] },
  { nome: "anexo", zoom: 18.0, center: [-46.6343, -23.5167] },
  { nome: "detalhe", zoom: 19.5, center: [-46.637, -23.5164] },
];

const browser = await chromium.launch({ args: ["--use-angle=swiftshader"] });
const page = await browser.newPage({ viewport: { width: 900, height: 650 } });
await page.goto("http://localhost:8027/", { waitUntil: "networkidle" });
await page.waitForTimeout(3000);
for (const v of vistas) {
  await page.evaluate((vv) => {
    window.__map.jumpTo({ center: vv.center, zoom: vv.zoom, bearing: 4 });
  }, v);
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `shot-${v.nome}.png` });
  console.log(`shot-${v.nome}.png`);
}
await browser.close();
