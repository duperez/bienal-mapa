/**
 * Teste do modo offline.
 *
 * É o requisito que decidiu a arquitetura do app: sem rede lá dentro, e por
 * isso sem GPS, sem tile remoto e sem busca no servidor. Testar isso "olhando
 * se o service worker registrou" não vale nada — o que vale é ficar sem
 * servidor, recarregar e montar um percurso.
 *
 * O teste MATA o servidor em vez de usar context.setOffline(). Não é
 * preciosismo: o setOffline do Playwright derruba subresource (script, css)
 * antes de a request chegar ao service worker, então ele reprova um app que
 * funciona. Matar o processo é a situação real — o SW responde, a rede é que
 * não existe.
 *
 * Roda contra o BUILD, que ele mesmo sobe: em dev o SW nem é registrado.
 *
 * Uso: node test-offline.mjs   (opcional: porta, padrão 4199)
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";

const porta = process.argv[2] || "4199";
const base = `http://localhost:${porta}/`;

const falhas = [];
const ok = (cond, msg) => {
  console.log(`${cond ? "ok  " : "FALHA"} ${msg}`);
  if (!cond) falhas.push(msg);
};

// o binário direto, não npx: o npx sai antes e deixa o vite órfão, e aí o
// teste "offline" acabaria rodando com rede sem ninguém perceber
const servidor = spawn("node_modules/.bin/vite", ["preview", "--port", porta], {
  stdio: "ignore",
});
const derruba = () => {
  try {
    servidor.kill("SIGKILL");
  } catch {
    /* já morreu */
  }
};
const espera = (ms) => new Promise((r) => setTimeout(r, ms));
await espera(4000);

const navegador = await chromium.launch();
const pagina = await navegador.newPage({ viewport: { width: 900, height: 1000 } });
const erros = [];
pagina.on("pageerror", (e) => erros.push(String(e.message)));

try {
  // 1. primeira visita, com servidor no ar: o SW instala e enche o cache
  await pagina.goto(base, { waitUntil: "networkidle" });
  await pagina.waitForTimeout(2000);

  const cache = await pagina.evaluate(async () => {
    const reg = await navigator.serviceWorker.ready;
    const nomes = await caches.keys();
    const c = await caches.open(nomes[0]);
    const urls = (await c.keys()).map((r) => decodeURIComponent(new URL(r.url).pathname));
    const precisa = [
      "/data/mapa.geojson",
      "/data/malha.json",
      "/data/venue.geojson",
      "/glyphs/Klokantech Noto Sans Regular/0-255.pbf",
      "/manifest.webmanifest",
      "/icon-192.png",
    ];
    return {
      ativo: reg.active?.state === "activated",
      caches: nomes.length,
      itens: urls.length,
      falta: precisa.filter((p) => !urls.some((u) => u.endsWith(p))),
    };
  });
  console.log(`caches: ${cache.caches} · itens no precache: ${cache.itens}`);
  ok(cache.ativo, "service worker ativa na primeira visita");
  ok(cache.caches === 1, `um único cache ativo (${cache.caches})`);
  ok(
    cache.falta.length === 0,
    `dado e glifo no precache (falta: ${cache.falta.join(", ") || "nada"})`,
  );

  // 2. servidor morto. Daqui para baixo não existe rede: o que responder,
  //    responde do cache.
  derruba();
  await espera(1500);
  const morreu = await fetch(base)
    .then(() => false)
    .catch(() => true);
  ok(morreu, "servidor realmente fora do ar");

  erros.length = 0;
  await pagina.reload({ waitUntil: "domcontentloaded" });
  await pagina.waitForTimeout(4500);

  ok((await pagina.locator("#map canvas").count()) > 0, "mapa desenha sem servidor");
  ok((await pagina.locator("#searchInput").count()) > 0, "interface monta sem servidor");

  const dados = await pagina.evaluate(async () => {
    const [mapa, malha] = await Promise.all([
      fetch("./data/mapa.geojson").then((r) => r.json()),
      fetch("./data/malha.json").then((r) => r.json()),
    ]);
    return { features: mapa.features.length, destinos: Object.keys(malha.acessos).length };
  });
  ok(dados.features > 400, `geojson completo do cache (${dados.features} features)`);
  ok(dados.destinos > 250, `malha completa do cache (${dados.destinos} destinos)`);

  // 3. o teste que vale: montar um percurso inteiro pela interface, sem rede
  // busca, abre a ficha do primeiro resultado e manda para o percurso — o
  // mesmo gesto do visitante
  const buscar = async (termo) => {
    await pagina.fill("#searchInput", termo);
    await pagina.waitForTimeout(600);
    await pagina.click("#searchResults > *:first-child");
    await pagina.waitForTimeout(700);
    await pagina.click("#sheetRota");
    await pagina.waitForTimeout(1500);
  };
  await buscar("Companhia das Letras");
  const total = (await pagina.textContent("#rotaTotal")) ?? "";
  ok(/\d+ m/.test(total), `rota traçada offline (${total.trim() || "vazio"})`);

  await buscar("Auditório");
  const paradas = await pagina.locator(".rota-linha").count();
  ok(paradas >= 3, `parada adicionada offline (${paradas} paradas)`);

  await pagina.click('.rota-emenda[data-i="1"] .rota-mais');
  await pagina.waitForTimeout(300);
  const passos = await pagina.locator(".rota-passo").count();
  const primeiro = (await pagina.locator(".rota-passo").first().textContent()) ?? "";
  ok(passos >= 2, `instruções passo a passo offline (${passos} passos: "${primeiro.trim()}"…)`);

  ok(erros.length === 0, `nenhum erro de página offline (${erros.slice(0, 2).join(" | ")})`);
} finally {
  await navegador.close();
  derruba();
}

console.log(falhas.length ? `\n${falhas.length} falha(s)` : "\ntudo certo");
process.exit(falhas.length ? 1 : 0);
