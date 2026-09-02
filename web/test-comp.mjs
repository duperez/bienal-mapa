import { chromium } from "playwright";
const vistas = [
  { nome: "geral", zoom: 16.4, center: [-46.635996, -23.516565] },
  { nome: "NO", zoom: 17.6, center: [-46.637048, -23.515948] },
  { nome: "NE", zoom: 17.6, center: [-46.635547, -23.516044] },
  { nome: "SO", zoom: 17.6, center: [-46.637118, -23.516863] },
  { nome: "SE-anexo", zoom: 17.2, center: [-46.635269, -23.517038] },
];
const browser = await chromium.launch({ args: ["--use-angle=swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1100, height: 700 } });
await page.goto("http://localhost:8027/", { waitUntil: "networkidle" });
await page.waitForTimeout(3000);
for (const v of vistas) {
  await page.evaluate((vv) => {
    window.__map.jumpTo({ center: vv.center, zoom: vv.zoom, bearing: 4 });
  }, v);
  await page.waitForTimeout(1300);
  await page.screenshot({ path: `comp-${v.nome}-atual.png` });
  console.log(v.nome);
}
await browser.close();
