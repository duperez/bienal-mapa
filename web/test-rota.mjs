// Teste da rota: um percurso real ponta a ponta no app, e depois carga.
// O A* roda no navegador, então o teste também precisa rodar lá — medir a
// versão Python não diria nada sobre o que o visitante usa.
//
//   node test-rota.mjs <porta>
import { chromium } from "playwright";

const porta = process.argv[2] ?? "5173";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 900, height: 1000 } });
p.on("console", (m) => m.type() === "error" && console.log("ERRO:", m.text()));
await p.goto(`http://localhost:${porta}`, { waitUntil: "networkidle" });
await p.waitForTimeout(2500);

const buscar = async (termo) => {
  await p.fill("#searchInput", termo);
  await p.waitForTimeout(600);
  await p.click("#searchResults > *:first-child");
  await p.waitForTimeout(1000);
};

// 1. destino primeiro, origem assumida — o caminho comum
await buscar("Companhia das Letras");
console.log("ficha :", await p.textContent("#sheetTitle"), "|", await p.textContent("#sheetSub"));
await p.click("#sheetRota");
await p.waitForTimeout(1600);
console.log("origem:", (await p.textContent("#rotaOrigem .rota-texto")).trim());
console.log("rota  :", await p.textContent("#rotaResumo"));
await p.screenshot({ path: "shot-rota.png" });

// 2. trocar a origem por busca: "estou no estande X"
await p.click("#rotaOrigem");
await p.waitForTimeout(300);
console.log("dica  :", await p.textContent("#rotaResumo"));
await buscar("Sextante");
await p.waitForTimeout(1400);
console.log("origem:", (await p.textContent("#rotaOrigem .rota-texto")).trim());
console.log("rota  :", await p.textContent("#rotaResumo"));
await p.screenshot({ path: "shot-percurso.png" });

// 3. inverter
const antes = await p.textContent("#rotaResumo");
await p.click("#rotaTrocar");
await p.waitForTimeout(1200);
console.log(`trocar: ${antes} -> ${await p.textContent("#rotaResumo")}`);

// 3b. toque livre em corredor vira "Ponto no mapa" (o snap resolve o dedo
// impreciso). Alvo escolhido pela própria malha e projetado para pixel, para
// o teste não depender de eu adivinhar um vão na tela.
await p.click("#rotaOrigem");
await p.waitForTimeout(300);
const alvo = await p.evaluate(async () => {
  const m = await (await fetch("/data/malha.json")).json();
  const { Rotas } = await import("/src/rotas.ts");
  const R = new Rotas(m);
  const map = window.__map;
  for (let j = 0; j < m.h; j++) {
    for (let i = 0; i < m.w; i++) {
      // exige vizinhança toda livre: garante corredor, não borda de estande
      if (![-2, 0, 2].every((a) => [-2, 0, 2].every((b) => R.livreEm(i + a, j + b)))) continue;
      const pt = map.project(R.lngLat([i, j]));
      if (pt.x > 120 && pt.x < 780 && pt.y > 120 && pt.y < 700) return [pt.x, pt.y];
    }
  }
  return null;
});
await p.mouse.click(alvo[0], alvo[1]);
await p.waitForTimeout(1200);
const porToque = (await p.textContent("#rotaOrigem .rota-texto")).trim();
console.log("toque :", porToque, "|", await p.textContent("#rotaResumo"));

// 3c. e volta para um estande, que é a origem que o teste seguinte espera
await p.click("#rotaOrigem");
await p.waitForTimeout(300);
await buscar("Companhia das Letras");
await p.waitForTimeout(1200);

// 4. a origem tem que sobreviver ao reload (visitante não redefine a cada
// busca). Depois do passo 3 a origem lembrada é a Companhia das Letras, que
// virou origem ao inverter o percurso.
await p.reload({ waitUntil: "networkidle" });
await p.waitForTimeout(2500);
await buscar("Intrínseca");
await p.click("#sheetRota");
await p.waitForTimeout(1500);
const lembrada = (await p.textContent("#rotaOrigem .rota-texto")).trim();
console.log("lembra:", lembrada, "|", await p.textContent("#rotaResumo"));

// 5. carga: rota entre pares de estandes quaisquer, que é o uso real agora
const r = await p.evaluate(async () => {
  const m = await (await fetch("/data/malha.json")).json();
  const { Rotas } = await import("/src/rotas.ts");
  const R = new Rotas(m);
  const chaves = Object.keys(m.acessos);

  // porta -> estande: garante que ninguém fica ilhado das entradas
  const semPorta = chaves.filter((k) => !R.daPortaMaisProxima(m.acessos[k]));

  // estande -> estande: sorteio determinístico (LCG) para o número não
  // dançar entre execuções
  let s = 7;
  const rnd = () => ((s = (s * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
  const dists = [];
  let falhas = 0;
  let curvas = 0;
  const t0 = performance.now();
  for (let n = 0; n < 300; n++) {
    const a = m.acessos[chaves[(rnd() * chaves.length) | 0]];
    const z = m.acessos[chaves[(rnd() * chaves.length) | 0]];
    const rota = R.rota(a, z);
    if (!rota) {
      falhas++;
      continue;
    }
    dists.push(rota.metros);
    curvas += rota.cels.length;
  }
  const ms = performance.now() - t0;
  dists.sort((x, y) => x - y);

  // snap: um ponto qualquer no meio do salão tem que achar corredor perto
  const centro = R.lngLat([(m.w / 2) | 0, (m.h / 2) | 0]);

  return {
    destinos: chaves.length,
    semPorta: semPorta.length,
    falhas,
    ms_por_par: +(ms / 300).toFixed(1),
    mediana_m: Math.round(dists[dists.length >> 1]),
    max_m: Math.round(dists[dists.length - 1]),
    curvas_medias: +(curvas / dists.length).toFixed(1),
    snap: !!R.maisProximaLivre(centro[0], centro[1], 25),
  };
});
console.log(
  `destinos ${r.destinos} · sem porta ${r.semPorta} · ` +
    `pares 300 · sem rota ${r.falhas} · mediana ${r.mediana_m} m · ` +
    `máx ${r.max_m} m · ${r.curvas_medias} curvas · ${r.ms_por_par} ms/par · snap ${r.snap}`,
);
await b.close();
const ok = porToque === "Ponto no mapa" && !r.falhas && !r.semPorta && r.snap && lembrada.includes("Companhia");
if (!ok) console.log("FALHOU");
process.exit(ok ? 0 : 1);
