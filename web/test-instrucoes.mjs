/**
 * Teste das instruções passo a passo.
 *
 * A checagem que importa é a lateralidade. "Vire à esquerda" é a única parte
 * do app que pode estar errada em silêncio: o traçado desenhado continua
 * certinho na tela mesmo com o sinal trocado, então nenhum olhar no mapa pega
 * o defeito — só quem estiver no corredor. Por isso aqui a virada é recalculada
 * do zero em coordenadas geográficas de verdade (leste/norte em metros), sem
 * usar nada do frame de células, e comparada com o que o módulo respondeu.
 *
 * Uso: node test-instrucoes.mjs [porta]
 */
import { chromium } from "playwright";

const porta = process.argv[2] || "5173";
const PARES = 120;

const navegador = await chromium.launch();
const pagina = await navegador.newPage();
const erros = [];
pagina.on("pageerror", (e) => erros.push(String(e.message)));
await pagina.goto(`http://localhost:${porta}/`, { waitUntil: "networkidle" });

const r = await pagina.evaluate(async (PARES) => {
  const [mapa, malha] = await Promise.all([
    fetch("/data/mapa.geojson").then((r) => r.json()),
    fetch("/data/malha.json").then((r) => r.json()),
  ]);
  const { instrucoes, viasDaMalha } = await import("/src/instrucoes.ts");
  const { Rotas } = await import("/src/rotas.ts");
  const rotas = new Rotas(malha);
  const vias = viasDaMalha(mapa, rotas);
  const nomes = new Set(vias.map((v) => v.nome));

  // célula -> metros locais (leste, norte), sem passar pelo frame da malha
  const lat0 = rotas.lngLat([0, 0])[1];
  const kx = 111320 * Math.cos((lat0 * Math.PI) / 180);
  const geo = (c) => {
    const [lng, lat] = rotas.lngLat(c);
    return [lng * kx, lat * 111320];
  };

  const chaves = Object.keys(malha.acessos);
  const saida = {
    pares: 0,
    passos: 0,
    semVia: 0,
    viaFantasma: 0,
    ladoTrocado: 0,
    somaRuim: 0,
    semChegada: 0,
    exemplos: [],
  };

  for (let n = 0; n < PARES; n++) {
    const a = malha.acessos[chaves[(n * 7) % chaves.length]];
    const b = malha.acessos[chaves[(n * 31 + 13) % chaves.length]];
    const rota = rotas.rota(a, b);
    if (!rota || rota.metros < 25) continue;
    const passos = instrucoes(rota.cels, vias, rotas, "destino");
    saida.pares++;
    if (passos[passos.length - 1]?.virar !== "chegada") saida.semChegada++;

    const soma = passos.reduce((s, p) => s + p.metros, 0);
    if (Math.abs(soma - rota.metros) > 0.5) saida.somaRuim++;

    // A lateralidade é o único ponto que erra em silêncio: com o sinal
    // trocado o traçado desenhado continua certo e só quem está no corredor
    // percebe. Cada passo publica os dois rumos que decidiram o lado, em
    // células; aqui eles são convertidos para metros de verdade (leste/norte)
    // e o lado é recalculado do zero, sem tocar no frame da malha.
    //
    // Varrer vértice a vértice, como este teste fazia antes, media outra coisa:
    // duas guinadas de 20 graus seguidas somam 40 depois da fusão de trechos,
    // e o teste acusava a instrução certa de estar sobrando.
    for (const p of passos) {
      if (!p.giro) continue;
      const o = geo(p.giro.base);
      const uu = geo([p.giro.base[0] + p.giro.u[0], p.giro.base[1] + p.giro.u[1]]);
      const vv = geo([p.giro.base[0] + p.giro.v[0], p.giro.base[1] + p.giro.v[1]]);
      const u = [uu[0] - o[0], uu[1] - o[1]];
      const v = [vv[0] - o[0], vv[1] - o[1]];
      const lado = u[0] * v[1] - u[1] * v[0] > 0 ? "esquerda" : "direita";
      if (lado !== p.virar) {
        saida.ladoTrocado++;
        if (saida.exemplos.length < 3) saida.exemplos.push({ dito: p.virar, real: lado, texto: p.texto });
        break;
      }
    }

    for (const p of passos) {
      saida.passos++;
      if (!p.via && p.virar !== "chegada") saida.semVia++;
      if (p.via && !nomes.has(p.via)) saida.viaFantasma++;
    }
  }
  return saida;
}, PARES);

await navegador.close();

const falhas = [];
const ok = (cond, msg) => {
  console.log(`${cond ? "ok  " : "FALHA"} ${msg}`);
  if (!cond) falhas.push(msg);
};

console.log(`pares roteados: ${r.pares} · passos gerados: ${r.passos}`);
ok(r.pares > 80, `pelo menos 80 pares roteáveis (${r.pares})`);
ok(erros.length === 0, `nenhum erro de página (${erros.join(" | ")})`);
ok(r.semChegada === 0, `toda rota termina com "Chegou" (${r.semChegada} sem)`);
ok(r.viaFantasma === 0, `nenhum nome de via inventado (${r.viaFantasma})`);
ok(r.somaRuim === 0, `metros dos passos batem com a rota (${r.somaRuim} fora)`);
ok(
  r.ladoTrocado === 0,
  `lateralidade confere no referencial geográfico (${r.ladoTrocado} rotas com lado trocado)` +
    (r.exemplos.length ? ` ex: ${JSON.stringify(r.exemplos[0])}` : ""),
);
const semNome = (100 * r.semVia) / Math.max(1, r.passos - r.pares);
// era 25%, com a regra de ângulo. A regra de cobertura mais o teto de largura
// corrigido no build derrubaram para ~14%; o limite acompanha, senão ele para
// de guardar coisa nenhuma.
ok(semNome < 17, `menos de 17% dos passos sem nome de via (${semNome.toFixed(1)}%)`);

console.log(falhas.length ? `\n${falhas.length} falha(s)` : "\ntudo certo");
process.exit(falhas.length ? 1 : 0);
