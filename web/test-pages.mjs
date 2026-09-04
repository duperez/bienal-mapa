/**
 * Teste da publicação: o app servido como o GitHub Pages serve.
 *
 * O app não mora na raiz de um domínio, mora em
 * `https://duperez.github.io/bienal-mapa/`. Isso quebra tudo que assume "/":
 * o bundle, os dados, os glifos, o manifest, o registro do service worker e o
 * escopo dele. E quebra calado — em `vite preview` e em `vite dev` a base é a
 * raiz, então todos os outros testes passam com o app publicado quebrado.
 *
 * Por isso este teste sobe um servidor estático próprio em vez de reusar o
 * `vite preview`: ele monta o dist embaixo de um prefixo e devolve 404 puro
 * para o que não existe, sem fallback de SPA, que é o comportamento do Pages.
 * Um `index.html` de consolo esconderia justamente o defeito procurado.
 *
 * A segunda metade é o offline no subcaminho: o service worker guarda URLs, e
 * uma URL com prefixo errado enche o cache de lixo que só falha sem rede.
 *
 * Roda contra o BUILD, que ele mesmo sobe.
 *
 * Uso: node test-pages.mjs   (opcional: porta, padrão 4198)
 */
import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { join, extname, normalize } from "node:path";

const porta = process.argv[2] || "4198";
/** o mesmo prefixo do Pages: o nome do repositório */
const PREFIXO = "/bienal-mapa";
const base = `http://localhost:${porta}${PREFIXO}/`;

const falhas = [];
const ok = (cond, msg) => {
  console.log(`${cond ? "ok  " : "FALHA"} ${msg}`);
  if (!cond) falhas.push(msg);
};

const TIPOS = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".geojson": "application/json",
  ".webmanifest": "application/manifest+json",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".pbf": "application/x-protobuf",
};

const pedidos = [];
const servidor = createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  const caminho = decodeURIComponent(url.pathname);
  pedidos.push(caminho);
  if (!caminho.startsWith(`${PREFIXO}/`)) {
    res.writeHead(404).end("fora do prefixo");
    return;
  }
  let rel = caminho.slice(PREFIXO.length + 1) || "index.html";
  if (rel.endsWith("/")) rel += "index.html";
  const arq = join("dist", normalize(rel).replace(/^(\.\.[/\\])+/, ""));
  try {
    if ((await stat(arq)).isDirectory()) throw new Error("dir");
    const corpo = await readFile(arq);
    // Vary é o que quebrou o cache antes: o servidor real manda, então este
    // manda também, senão o teste seria mais fácil que a realidade
    res.writeHead(200, {
      "content-type": TIPOS[extname(arq)] || "application/octet-stream",
      vary: "Origin, Accept-Encoding",
    }).end(corpo);
  } catch {
    // 404 seco, como o Pages: sem index.html de consolo
    res.writeHead(404).end("não existe");
  }
});
await new Promise((r) => servidor.listen(Number(porta), r));

const navegador = await chromium.launch();
const pagina = await navegador.newPage({ viewport: { width: 900, height: 1000 } });
const erros = [];
const respostasRuins = [];
pagina.on("pageerror", (e) => erros.push(String(e.message)));
pagina.on("response", (r) => {
  if (r.status() >= 400) respostasRuins.push(`${r.status()} ${new URL(r.url()).pathname}`);
});

try {
  await pagina.goto(base, { waitUntil: "networkidle" });
  await pagina.waitForFunction(() => window.__map?.isStyleLoaded?.());
  await pagina.waitForTimeout(2500);

  ok(respostasRuins.length === 0, `nenhum 404 no subcaminho (${respostasRuins.join(", ") || "—"})`);
  ok(erros.length === 0, `nenhum erro de página (${erros[0] || "—"})`);

  // nada pode ter sido pedido na raiz: é o sintoma de base absoluta esquecida
  const naRaiz = pedidos.filter((p) => !p.startsWith(`${PREFIXO}/`) && p !== "/favicon.ico");
  ok(naRaiz.length === 0, `nada é pedido fora do prefixo (${naRaiz.join(", ") || "—"})`);

  const dados = await pagina.evaluate(() => ({
    estandes: window.__map.querySourceFeatures("mapa").length,
    escopo: "",
  }));
  ok(dados.estandes > 0, `o mapa carregou dados (${dados.estandes} feições na fonte)`);

  const sw = await pagina.evaluate(async () => {
    const reg = await navigator.serviceWorker.ready;
    const nomes = await caches.keys();
    const urls = (await (await caches.open(nomes[0])).keys()).map((r) => new URL(r.url).pathname);
    return {
      ativo: reg.active?.state === "activated",
      escopo: new URL(reg.scope).pathname,
      itens: urls.length,
      foraDoPrefixo: urls.filter((u) => !u.startsWith("/bienal-mapa/")),
    };
  });
  ok(sw.ativo, "service worker ativo");
  ok(sw.escopo === `${PREFIXO}/`, `escopo do SW é o subcaminho (${sw.escopo})`);
  ok(sw.itens >= 15, `precache cheio (${sw.itens} itens)`);
  ok(sw.foraDoPrefixo.length === 0, `nada cacheado fora do prefixo (${sw.foraDoPrefixo[0] || "—"})`);

  // Traçar uma rota AINDA COM SERVIDOR é o que pega pedido faltando. Antes esta
  // parte só rodava offline, e aí um 404 vira uma falha de fetch silenciosa,
  // sem resposta para o listener ver: foi assim que um glifo ausente passou
  // batido até o app estar publicado.
  await pagina.fill("#searchInput", "Rocco");
  await pagina.waitForTimeout(500);
  await pagina.click("#searchResults > *:first-child");
  await pagina.waitForTimeout(400);
  await pagina.click("#sheetRota");
  await pagina.waitForTimeout(1500);
  ok(
    respostasRuins.length === 0,
    `nenhum 404 ao traçar rota com servidor no ar (${respostasRuins.join(", ") || "—"})`,
  );
  await pagina.click("#rotaFechar").catch(() => {});
  await pagina.waitForTimeout(300);

  // ---- agora sem servidor, que é o dia do evento ----
  await new Promise((r) => servidor.close(r));
  servidor.closeAllConnections?.();

  const errosOffline = [];
  pagina.on("pageerror", (e) => errosOffline.push(String(e.message)));
  await pagina.reload({ waitUntil: "load" });
  await pagina.waitForFunction(() => window.__map?.isStyleLoaded?.());
  await pagina.waitForTimeout(2000);

  const semRede = await pagina.evaluate(() => window.__map.querySourceFeatures("mapa").length);
  ok(semRede > 0, `abre sem servidor nenhum (${semRede} feições)`);
  ok(errosOffline.length === 0, `nenhum erro offline (${errosOffline[0] || "—"})`);

  // e roteia, que é para o que o app existe
  await pagina.fill("#searchInput", "Rocco");
  await pagina.waitForTimeout(500);
  await pagina.click("#searchResults > *:first-child");
  await pagina.waitForTimeout(400);
  await pagina.click("#sheetRota");
  await pagina.waitForTimeout(400);
  await pagina.fill("#searchInput", "Espaço Educação");
  await pagina.waitForTimeout(500);
  await pagina.click("#searchResults > *:first-child");
  await pagina.waitForTimeout(400);
  await pagina.click("#sheetRota");
  await pagina.waitForTimeout(1200);
  const total = await pagina.textContent("#rotaTotal");
  ok(/\d+\s*m/.test(total || ""), `traça rota sem rede (${total?.trim()})`);
} finally {
  await navegador.close();
  try {
    servidor.close();
    servidor.closeAllConnections?.();
  } catch {
    /* já fechado */
  }
}

console.log(falhas.length ? `\n${falhas.length} falha(s)` : "\ntudo certo");
process.exit(falhas.length ? 1 : 0);
