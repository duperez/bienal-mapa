// Teste da rota: um caminho real ponta a ponta no app, e depois todos os
// destinos de uma vez. O A* roda no navegador, então o teste também precisa
// rodar lá — medir a versão Python não diria nada sobre o que o visitante usa.
//
//   node test-rota.mjs <porta>
import { chromium } from "playwright";

const porta = process.argv[2] ?? "5173";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 900, height: 1000 } });
p.on("console", (m) => m.type() === "error" && console.log("ERRO:", m.text()));
await p.goto(`http://localhost:${porta}`, { waitUntil: "networkidle" });
await p.waitForTimeout(2500);

// 1. caminho visível, do jeito que o visitante faz
await p.fill("#searchInput", "Companhia das Letras");
await p.waitForTimeout(600);
await p.click("#searchResults > *:first-child");
await p.waitForTimeout(1200);
console.log("ficha:", await p.textContent("#sheetTitle"), "|", await p.textContent("#sheetSub"));
await p.click("#sheetRota");
await p.waitForTimeout(1600);
console.log("rota :", await p.textContent("#sheetSub"));
await p.screenshot({ path: "shot-rota.png" });
console.log("shot-rota.png");

// 2. todos os destinos: nenhum estande pode ficar sem caminho
const r = await p.evaluate(async () => {
  const m = await (await fetch("/data/malha.json")).json();
  const { Rotas } = await import("/src/rotas.ts");
  const R = new Rotas(m);
  const chaves = Object.keys(m.acessos);
  const t0 = performance.now();
  const falhas = [];
  const dists = [];
  let curvas = 0;
  for (const k of chaves) {
    const best = R.daPortaMaisProxima(m.acessos[k]);
    if (!best) {
      falhas.push(k);
      continue;
    }
    dists.push(best.metros);
    curvas += R.enxuga(best.cels).length;
  }
  const ms = performance.now() - t0;
  dists.sort((a, b) => a - b);
  return {
    destinos: chaves.length,
    falhas,
    ms_por_destino: +(ms / chaves.length).toFixed(1),
    mediana_m: Math.round(dists[dists.length >> 1]),
    max_m: Math.round(dists[dists.length - 1]),
    curvas_medias: +(curvas / dists.length).toFixed(1),
  };
});
console.log(
  `destinos ${r.destinos} · sem rota ${r.falhas.length} · ` +
    `mediana ${r.mediana_m} m · máx ${r.max_m} m · ` +
    `${r.curvas_medias} curvas · ${r.ms_por_destino} ms/destino`,
);
await b.close();
process.exit(r.falhas.length ? 1 : 0);
