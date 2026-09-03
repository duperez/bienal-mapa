// Screenshots do app real: várias vistas do mapa renderizado no browser.
// Uso: node test-shots.mjs [porta]
import { chromium } from "playwright";

const porta = process.argv[2] ?? "5173";
const vistas = [
  // "abertura" usa o enquadramento inicial do próprio app (sem jumpTo)
  { nome: "abertura" },
  { nome: "miolo", zoom: 18.0, center: [-46.6371, -23.5164] },
  { nome: "nordeste", zoom: 18.0, center: [-46.6356, -23.516] },
  { nome: "anexo", zoom: 18.2, center: [-46.6349, -23.5167] },
  { nome: "detalhe", zoom: 19.6, center: [-46.6369, -23.5165] },
];

const browser = await chromium.launch({ args: ["--use-angle=swiftshader"] });
const page = await browser.newPage({
  viewport: { width: 960, height: 680 },
  deviceScaleFactor: 2,
});
page.on("console", (m) => m.type() === "error" && console.log("console:", m.text()));
await page.goto(`http://localhost:${porta}/`, { waitUntil: "networkidle" });
await page.waitForFunction(() => window.__map?.isStyleLoaded?.(), null, { timeout: 30000 });
await page.waitForTimeout(2500);

for (const v of vistas) {
  if (v.center) {
    await page.evaluate((vv) => {
      window.__map.jumpTo({ center: vv.center, zoom: vv.zoom, bearing: 4 });
    }, v);
  }
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `shot-${v.nome}.png` });
  console.log(`shot-${v.nome}.png`);
}
await browser.close();
