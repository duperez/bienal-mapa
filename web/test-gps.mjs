// Teste do GPS com emulação real do navegador (Playwright), não com o modo
// de simulação do app: o que interessa aqui é o caminho que roda no dia, com
// a API `navigator.geolocation` de verdade — permissão, precisão e silêncio.
//
//   node test-gps.mjs <porta>
import { chromium } from "playwright";

const porta = process.argv[2] ?? "5173";
const nav = await chromium.launch();

/** abre o app com um fix emulado (ou sem nenhum) e devolve a página */
async function abre({ fix, permitir = true, pendura = false }) {
  const ctx = await nav.newContext({
    viewport: { width: 900, height: 1000 },
    permissions: permitir ? ["geolocation"] : [],
    geolocation: fix,
  });
  const p = await ctx.newPage();
  if (pendura) {
    // silêncio absoluto: nem sucesso nem erro. É o desfecho mais comum
    // dentro de pavilhão e o que trava a tela se o app não tiver relógio.
    await p.addInitScript(() => {
      navigator.geolocation.getCurrentPosition = () => {};
      navigator.geolocation.watchPosition = () => 1;
    });
  }
  p.on("console", (m) => m.type() === "error" && console.log("ERRO:", m.text()));
  await p.goto(`http://localhost:${porta}`, { waitUntil: "networkidle" });
  await p.waitForTimeout(2200);
  return { ctx, p };
}

/** posições reais do desenho, tiradas da própria malha */
const { ctx: c0, p: p0 } = await abre({ fix: { latitude: 0, longitude: 0 } });
const lugares = await p0.evaluate(async () => {
  const m = await (await fetch("/data/malha.json")).json();
  const { Rotas } = await import("/src/rotas.ts");
  const R = new Rotas(m);
  const [nome, cel] = Object.entries(m.portas)[0];
  const meio = R.acesso(Object.keys(m.acessos)[Math.floor(Object.keys(m.acessos).length / 2)]);
  const ll = (c) => ({ longitude: R.lngLat(c)[0], latitude: R.lngLat(c)[1] });
  // um ponto ~600 m a oeste: fora do pavilhão sem ambiguidade
  const fora = R.lngLat(meio);
  return {
    porta: { nome, ...ll(cel[0]) },
    meio: ll(meio),
    fora: { longitude: fora[0] - 0.006, latitude: fora[1] },
  };
});
await c0.close();

/** roda o fluxo até a mensagem do painel */
async function cenario(nome, opts, depois) {
  const { ctx, p } = await abre(opts);
  await p.evaluate(() => localStorage.clear());
  await p.reload({ waitUntil: "networkidle" });
  await p.waitForTimeout(2200);
  await p.fill("#searchInput", "Companhia das Letras");
  await p.waitForTimeout(500);
  await p.click("#searchResults > *:first-child");
  await p.waitForTimeout(800);
  await p.click("#sheetRota");
  await p.waitForTimeout(1200);
  await p.click("#rotaGps");
  await p.waitForTimeout(opts.pendura ? 8000 : 5000);
  const out = {
    resumo: (await p.textContent("#rotaResumo")).trim(),
    origem: (await p.textContent("#rotaOrigem .rota-texto")).trim(),
    lista: await p.locator(".rota-op").count(),
    escolhendo: await p.locator("#rotaOrigem.ativo").count(),
  };
  if (depois) await depois(p);
  console.log(
    `${nome.padEnd(22)} origem="${out.origem}" lista=${out.lista} ` +
      `pedindo=${out.escolhendo}\n${" ".repeat(24)}${out.resumo}`,
  );
  await ctx.close();
  return out;
}

const r = {};

// 1. fix bom em cima de uma porta: o GPS pode decidir sozinho
r.porta = await cenario("porta, ±15 m", {
  fix: { ...lugares.porta, accuracy: 15 },
});

// 2. fix bom no meio do salão: o GPS não decide, só ordena candidatos
r.meio = await cenario("meio do salão, ±30 m", {
  fix: { ...lugares.meio, accuracy: 30 },
}, (p) => p.screenshot({ path: "shot-gps.png" }));

// 2b/2c. a lista tem que encolher com sinal bom e crescer com sinal ruim —
// é o `accuracy` (raio de 95% de confiança) definindo o perímetro, não eu
r.preciso = await cenario("meio do salão, ±8 m", {
  fix: { ...lugares.meio, accuracy: 8 },
});
r.vago = await cenario("meio do salão, ±60 m", {
  fix: { ...lugares.meio, accuracy: 60 },
});

// 3. erro grande demais: o círculo não informaria nada
r.ruim = await cenario("sinal fraco, ±200 m", {
  fix: { ...lugares.meio, accuracy: 200 },
});

// 4. fora do pavilhão
r.fora = await cenario("fora do pavilhão", {
  fix: { ...lugares.fora, accuracy: 20 },
});

// 5. permissão negada
r.negado = await cenario("permissão negada", {
  fix: { ...lugares.meio, accuracy: 20 },
  permitir: false,
});

// 6. fix pendurado: nunca responde
r.pendurado = await cenario("fix pendurado", {
  fix: { ...lugares.meio, accuracy: 20 },
  pendura: true,
});

// 7. modo de simulação (?gps=sim): o que o dono do projeto usa no navegador
// para testar sem estar no Anhembi. Precisa se anunciar como simulado.
const ctxSim = await nav.newContext({ viewport: { width: 900, height: 1000 }, permissions: [] });
const pSim = await ctxSim.newPage();
await pSim.goto(`http://localhost:${porta}/?gps=sim&erro=25`, { waitUntil: "networkidle" });
await pSim.waitForTimeout(2200);
const rotulo = await pSim.textContent("#rotaGps");
const badge = await pSim.locator("#avisoSim").count();
await pSim.keyboard.down("Shift");
await pSim.mouse.click(450, 300);
await pSim.keyboard.up("Shift");
await pSim.waitForTimeout(500);
const marcado = await pSim.evaluate(() => ({
  guardado: !!localStorage.getItem("bienal.gpsSim"),
  desenhado: window.__map.queryRenderedFeatures({ layers: ["gpsim-ponto"] }).length,
}));
await pSim.fill("#searchInput", "Companhia das Letras");
await pSim.waitForTimeout(500);
await pSim.click("#searchResults > *:first-child");
await pSim.waitForTimeout(800);
await pSim.click("#sheetRota");
await pSim.waitForTimeout(1000);
await pSim.click("#rotaGps");
await pSim.waitForTimeout(2000);
const simResumo = (await pSim.textContent("#rotaResumo")).trim();
console.log(`${"simulação (?gps=sim)".padEnd(22)} botão="${rotulo}" aviso=${badge} fix=${marcado.guardado} desenho=${marcado.desenhado}`);
console.log(`${" ".repeat(24)}${simResumo}`);
await pSim.screenshot({ path: "shot-gps-sim.png" });
await ctxSim.close();

await nav.close();

const checa = [
  ["porta vira origem sozinha", r.porta.origem === lugares.porta.nome && r.porta.lista === 0],
  ["meio do salão oferece lista", r.meio.lista >= 5 && r.meio.resumo.includes("por aqui")],
  ["lista escala com a precisão", r.preciso.lista < r.vago.lista && r.preciso.lista >= 3],
  ["sinal fraco cai no manual", r.ruim.escolhendo === 1 && r.ruim.resumo.includes("fraco")],
  ["fora do pavilhão é dito", r.fora.resumo.includes("fora do pavilhão")],
  ["negado cai no manual", r.negado.escolhendo === 1 && r.negado.resumo.includes("permiss")],
  ["pendurado não trava", r.pendurado.escolhendo === 1 && r.pendurado.resumo.includes("sinal")],
  ["simulação se anuncia", badge === 1 && rotulo.includes("simulada") && marcado.guardado && marcado.desenhado === 1],
  ["simulação produz fix", simResumo.includes("simulado")],
];
console.log();
for (const [nome, ok] of checa) console.log(`${ok ? "ok  " : "FALHA"} ${nome}`);
process.exit(checa.every(([, ok]) => ok) ? 0 : 1);
