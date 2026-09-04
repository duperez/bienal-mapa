// Teste do percurso: um roteiro real ponta a ponta no app, e depois carga.
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
const campo = (i) => p.textContent(`.rota-linha[data-i="${i}"] .rota-texto`).then((s) => s.trim());
const total = () => p.textContent("#rotaTotal");
const paradas = () => p.locator(".rota-linha").count();
const clicaCampo = async (i) => {
  await p.click(`.rota-linha[data-i="${i}"] .rota-campo`);
  await p.waitForTimeout(300);
};

// 1. destino primeiro, origem assumida — o caminho comum
await buscar("Companhia das Letras");
console.log("ficha :", await p.textContent("#sheetTitle"), "|", await p.textContent("#sheetSub"));
await p.click("#sheetRota");
await p.waitForTimeout(1600);
console.log("A→B   :", await campo(0), "->", await campo(1), "|", await total());
await p.screenshot({ path: "shot-rota.png" });

// 2. trocar a origem por busca: "estou no estande X"
await clicaCampo(0);
await buscar("Sextante");
await p.waitForTimeout(1400);
console.log("origem:", await campo(0), "|", await total());

// 3. terceira parada pelo botão da ficha: o gesto de montar roteiro
await buscar("Intrínseca");
const rotulo = await p.textContent("#sheetRota");
await p.click("#sheetRota");
await p.waitForTimeout(1600);
const tresParadas = await paradas();
console.log(`anexa : botão "${rotulo}" -> ${tresParadas} paradas |`, await total());
console.log("       ", await campo(0), "->", await campo(1), "->", await campo(2));

// 3b. cada trecho aparece entre as paradas, e a soma tem que fechar com o total
const emendas = (await p.locator(".rota-emenda").allTextContents()).map((s) => parseInt(s, 10));
const soma = emendas.reduce((a, c) => a + c, 0);
const totalM = parseInt(await total(), 10);
console.log(`trechos: ${emendas.join(" + ")} = ${soma} m (total ${totalM} m)`);

// 4. quarta parada por toque livre no mapa: o snap resolve o dedo impreciso.
// Alvo escolhido pela própria malha e projetado para pixel, para o teste não
// depender de eu adivinhar um vão na tela.
await p.click("#rotaAdd");
await p.waitForTimeout(400);
const alvo = await p.evaluate(async () => {
  const m = await (await fetch("/data/malha.json")).json();
  const { Rotas } = await import("/src/rotas.ts");
  const R = new Rotas(m);
  const map = window.__map;
  for (let j = 0; j < m.h; j++) {
    for (let i = 0; i < m.w; i++) {
      // exige vizinhança toda livre: garante corredor, não borda de estande
      if (![-2, 0, 2].every((a) => [-2, 0, 2].every((c) => R.livreEm(i + a, j + c)))) continue;
      const pt = map.project(R.lngLat([i, j]));
      if (pt.x > 120 && pt.x < 780 && pt.y > 120 && pt.y < 620) return [pt.x, pt.y];
    }
  }
  return null;
});
await p.mouse.click(alvo[0], alvo[1]);
await p.waitForTimeout(1400);
const porToque = await campo(3);
console.log("toque :", porToque, "|", await total(), `| ${await paradas()} paradas`);
await p.screenshot({ path: "shot-percurso.png" });

// 5. melhor ordem: só aparece com 4+ paradas e nunca pode piorar o total
const antesOrdem = parseInt(await total(), 10);
const temBotao = await p.isVisible("#rotaOtimiza");
await p.click("#rotaOtimiza");
await p.waitForTimeout(1600);
const depoisOrdem = parseInt(await total(), 10);
console.log(
  `ordem : ${antesOrdem} -> ${depoisOrdem} m | "${(await p.textContent("#rotaAviso")).trim()}"`,
);

// 6. inverter mantém o total (o grafo é simétrico) e troca as pontas
const pontaA = await campo(0);
await p.click("#rotaInverte");
await p.waitForTimeout(1400);
const inverteu = (await campo((await paradas()) - 1)) === pontaA;
const totalInv = parseInt(await total(), 10);
console.log(`inverte: ponta trocada ${inverteu} | ${totalInv} m`);

// 7. remover uma parada do meio encolhe a lista e o total
const nAntes = await paradas();
await p.click('.rota-linha[data-i="1"] button[data-acao="remove"]');
await p.waitForTimeout(1200);
const nDepois = await paradas();
console.log(`remove : ${nAntes} -> ${nDepois} paradas |`, await total());

// 8. o roteiro sobrevive ao reload (visitante não redefine a cada busca)
const origemAntes = await campo(0);
await p.reload({ waitUntil: "networkidle" });
await p.waitForTimeout(2500);
await buscar("Record");
await p.click("#sheetRota");
await p.waitForTimeout(1500);
const lembrada = await campo(0);
console.log(`lembra : "${origemAntes}" -> "${lembrada}"`);

// 9. carga: rota entre pares de estandes quaisquer, que é o uso real agora
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

  // O traçado tem que correr pelo meio do corredor, não de quina a quina.
  // Este era um defeito só de olho: a rota era válida (nunca atravessava
  // parede) e mesmo assim aparecia cortando o quarteirão na diagonal, porque
  // dentro de um corredor toda corda tem o mesmo comprimento do percurso pelo
  // meio, e o enxugamento por visibilidade escolhia a corda. Aqui a rota é
  // reamostrada célula a célula e se mede a folga até a parede.
  //
  // O critério é a folga MÉDIA e a fração do percurso colado na parede, não a
  // folga mínima: qualquer rota passa em algum momento por uma fresta de 2 m,
  // onde o melhor possível é 1 m de folga, então o mínimo é sempre o mesmo e
  // não discrimina nada. Medido no traçado que cortava as quinas: 0,29 m de
  // folga média e 96,5% do percurso colado. Corrigido: 2,44 m e 4,4%.
  let colado = 0;
  let folgaSoma = 0;
  let folgaN = 0;
  for (let n = 0; n < 120; n++) {
    const de = m.acessos[chaves[(n * 7) % chaves.length]];
    const para = m.acessos[chaves[(n * 31 + 13) % chaves.length]];
    const rt = R.rota(de, para);
    if (!rt || rt.metros < 40) continue;
    // as pontas são portas de estande, coladas na parede por definição
    for (let k = 2; k < rt.cels.length - 1; k++) {
      const [x0, y0] = rt.cels[k - 1];
      const [x1, y1] = rt.cels[k];
      const n2 = Math.max(1, Math.ceil(Math.hypot(x1 - x0, y1 - y0)));
      for (let s = 0; s <= n2; s++) {
        const f = R.folgaEm([x0 + ((x1 - x0) * s) / n2, y0 + ((y1 - y0) * s) / n2]);
        folgaSoma += f;
        folgaN++;
        if (f < 1) colado++;
      }
    }
  }

  return {
    pctColado: +((colado / Math.max(1, folgaN)) * 100).toFixed(1),
    folgaMedia: +(folgaSoma / Math.max(1, folgaN)).toFixed(2),
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
    `máx ${r.max_m} m · ${r.curvas_medias} curvas · ${r.ms_por_par} ms/par · snap ${r.snap} · ` +
    `folga média ${r.folgaMedia} m · colado ${r.pctColado}%`,
);
await b.close();

const checa = [
  ["anexa vira 3 paradas", tresParadas === 3],
  ["rótulo do botão muda", rotulo === "Adicionar ao percurso"],
  ["trechos somam o total", Math.abs(soma - totalM) <= emendas.length],
  ["toque vira ponto no mapa", porToque === "Ponto no mapa"],
  ["botão de ordem com 4 paradas", temBotao],
  ["melhor ordem não piora", depoisOrdem <= antesOrdem],
  ["inverter troca as pontas", inverteu],
  ["inverter mantém o total", Math.abs(totalInv - depoisOrdem) <= 2],
  ["remover encolhe a lista", nDepois === nAntes - 1],
  ["roteiro lembrado", lembrada === origemAntes],
  ["nenhum destino ilhado", !r.semPorta && !r.falhas && r.snap],
  ["traçado corre pelo meio do corredor", r.folgaMedia >= 2],
  ["traçado não corre colado na parede", r.pctColado <= 15],
];
const maus = checa.filter(([, ok]) => !ok);
for (const [nome] of maus) console.log("FALHOU:", nome);
process.exit(maus.length ? 1 : 0);
