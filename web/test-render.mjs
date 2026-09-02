// Teste de renderização real: Chromium headless com frames e WebGL.
// Uso: node test-render.mjs [url]
import { chromium } from "playwright";

const url = process.argv[2] ?? "http://localhost:8027/";
const browser = await chromium.launch({ args: ["--use-angle=swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1000, height: 700 } });

const logs = [];
page.on("console", (m) => logs.push(`[${m.type()}] ${m.text()}`));
page.on("pageerror", (e) => logs.push(`[pageerror] ${e.message}`));

await page.goto(url, { waitUntil: "networkidle" });
await page.waitForTimeout(3500);

const state = await page.evaluate(() => {
  const m = window.__map;
  if (!m) return { erro: "window.__map ausente" };
  const style = m.getStyle();
  const rendered = m.queryRenderedFeatures();
  const kinds = {};
  for (const f of rendered) {
    const k = f.properties?.kind ?? f.layer.id;
    kinds[k] = (kinds[k] ?? 0) + 1;
  }
  return {
    loaded: m.loaded(),
    styleLoaded: m.isStyleLoaded(),
    zoom: +m.getZoom().toFixed(2),
    center: m.getCenter(),
    bearing: m.getBearing(),
    nLayers: style?.layers?.length,
    sources: Object.keys(style?.sources ?? {}),
    renderedCount: rendered.length,
    renderedKinds: kinds,
  };
});

console.log(JSON.stringify(state, null, 1));
console.log("--- console da página ---");
for (const l of logs.slice(0, 20)) console.log(l);

await page.screenshot({ path: "test-render.png" });
console.log("screenshot: web/test-render.png");
await browser.close();
