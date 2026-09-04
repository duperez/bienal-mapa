import { defineConfig, type Plugin } from "vite";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { join, relative, sep } from "node:path";

/**
 * Escreve o service worker com a lista real do que o build produziu.
 *
 * A lista não é escrita à mão de propósito. O app precisa abrir sem rede
 * dentro do pavilhão — é o requisito que justificou tirar o GPS do projeto — e
 * uma lista mantida à mão erra calada: some um glifo, some um pedaço do
 * mapa.geojson, e o defeito só aparece no dia do evento, offline, sem
 * conserto. Varrendo o dist, qualquer arquivo novo entra no precache sozinho.
 *
 * A versão do cache é o hash do conteúdo de tudo. Uma publicação que não mudou
 * nada não invalida o cache de ninguém, e qualquer mudança real invalida — sem
 * número de versão para alguém esquecer de subir.
 */
function serviceWorker(): Plugin {
  return {
    name: "sw-do-bundle",
    apply: "build",
    closeBundle() {
      const dist = "dist";
      const arquivos: string[] = [];
      const anda = (dir: string) => {
        for (const nome of readdirSync(dir)) {
          const p = join(dir, nome);
          if (statSync(p).isDirectory()) anda(p);
          else arquivos.push(p);
        }
      };
      anda(dist);

      const lista = arquivos
        .map((p) => relative(dist, p).split(sep).join("/"))
        .filter((p) => p !== "sw.js")
        .sort();
      const h = createHash("sha256");
      let bytes = 0;
      for (const p of lista) {
        const conteudo = readFileSync(join(dist, ...p.split("/")));
        bytes += conteudo.length;
        h.update(p);
        h.update(conteudo);
      }
      const versao = h.digest("hex").slice(0, 12);

      const sw = `// gerado por vite.config.ts a partir do bundle — não editar à mão
const VERSAO = "bienal-${versao}";
const ARQUIVOS = ${JSON.stringify(["./", ...lista])};

// ignoreVary é obrigatório aqui, não é zelo: o servidor responde com Vary, e
// sem isso a mesma URL dá MISS quando a request vem de uma tag <script> (que
// manda Origin) em vez de um fetch() — o app abria sem estilo e sem código,
// só com os dados, e o defeito ia aparecer no evento.
const BUSCA = (req) => caches.match(req, { ignoreSearch: true, ignoreVary: true });

self.addEventListener("install", (e) => {
  // addAll é tudo-ou-nada: um 404 aborta a instalação e o SW antigo continua
  // servindo, que é melhor do que um cache pela metade
  e.waitUntil(
    caches.open(VERSAO).then((c) => c.addAll(ARQUIVOS)).then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== VERSAO).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== self.location.origin) return;

  // navegação sempre pelo shell em cache: num pavilhão a rede raramente cai de
  // vez, ela fica lenta, e esperar o timeout com a tela branca é pior que abrir
  if (req.mode === "navigate") {
    e.respondWith(BUSCA("./").then((r) => r || fetch(req)));
    return;
  }

  e.respondWith(
    BUSCA(req).then(
      (r) =>
        r ||
        fetch(req).then((resp) => {
          // guarda o que veio da rede sem estar previsto (um glifo de faixa
          // rara); falha de cache não pode derrubar a resposta
          if (resp.ok) {
            const copia = resp.clone();
            caches
              .open(VERSAO)
              .then((c) => c.put(req, copia))
              .catch(() => {});
          }
          return resp;
        }),
    ),
  );
});
`;
      writeFileSync(join(dist, "sw.js"), sw);
      console.log(
        `sw.js: ${lista.length} arquivos no precache (${(bytes / 1024).toFixed(0)} KB) · ${versao}`,
      );
    },
  };
}

export default defineConfig({
  // base relativa: o mesmo build funciona na raiz (servidor local) e em
  // subcaminho (GitHub Pages em /bienal-mapa/)
  base: "./",
  plugins: [serviceWorker()],
});
