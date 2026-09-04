/**
 * Instruções passo a passo a partir do traçado do A*.
 *
 * A linha desenhada resolve o problema de quem olha o mapa de cima. Quem está
 * dentro do pavilhão não tem essa vista: está no meio de um corredor de 3 m
 * entre duas paredes de estande de 3 m de altura, sem enxergar nem o teto nem
 * o fim da rua. O que orienta ali é a placa da rua — e ela existe, está no
 * desenho oficial, e o build já a extrai como feature `kind: "via"`.
 *
 * A regra é a mesma do resto do projeto: nada é inventado. Cada trecho só
 * ganha nome se houver uma via do PDF paralela a ele e perto o bastante; se
 * não houver, o passo sai sem nome ("siga em frente por 20 m") em vez de
 * receber um nome plausível. As vias cujo nome foi derivado (as transversais,
 * que o PDF numera mas não rotula) entram marcadas, para o app poder mostrar
 * a diferença.
 */

import type { Rotas } from "./rotas";

export interface Via {
  nome: string;
  derivado: boolean;
  /** extremos em células da malha */
  a: [number, number];
  b: [number, number];
  largura: number;
}

export interface Passo {
  /** "esquerda" | "direita" | "frente" | "chegada" | "partida" */
  virar: "esquerda" | "direita" | "frente" | "chegada" | "partida";
  via: string | null;
  derivado: boolean;
  metros: number;
  texto: string;
}

/** ângulo mínimo, em graus, para virar de fato — abaixo disso é desvio de corredor */
const VIRADA_MIN = 30;
/**
 * Folga lateral além da meia-largura da via, em metros.
 *
 * Não é chute: é o maior valor em que as faixas de duas ruas vizinhas ainda não
 * se encostam. As ruas do miolo (A a K) têm passo de 11,1 a 11,4 m entre
 * centros e largura de 4,2 a 5,6 m; medindo par a par, a folga máxima dá
 * 2,98 a 3,00 m em seis pares seguidos. Acima disso um passo na RUA E passaria
 * a caber também na faixa da RUA F, e a instrução viraria loteria.
 */
const FOLGA_M = 3.0;
/**
 * Fração do trecho que precisa correr dentro da faixa para a via valer.
 *
 * A regra anterior era ângulo mais o ponto do meio dentro da faixa, e errava
 * dos dois lados: reprovava quem anda pela rua em diagonal (o A* devolve o
 * corredor como uma corda inclinada, e 38% dos passos sem nome eram isso) e
 * não tinha o que dizer sobre quem só atravessa. Cobertura resolve as duas de
 * uma vez, e sem constante de ângulo: andar pela rua cobre quase tudo,
 * atravessar cobre a largura dela dividida pelo tamanho do passo.
 */
const COBERTURA_MIN = 0.7;
/** amostras ao longo do trecho para medir a cobertura */
const AMOSTRAS = 16;
/**
 * Abaixo disto um trecho sem nome não vira instrução própria.
 *
 * É a diagonal que se anda para sair de uma rua e entrar na outra pela boca da
 * transversal. 12 m cobre isso com folga (as transversais têm de 2,8 a 5,2 m
 * de largura e as ruas até 6,6 m) sem engolir um corredor curto de verdade.
 */
const CURTO_M = 12;

/** lê as vias do geojson e converte para células da malha */
export function viasDaMalha(geojson: GeoJSON.FeatureCollection, rotas: Rotas): Via[] {
  const out: Via[] = [];
  for (const f of geojson.features) {
    const p = f.properties as Record<string, unknown> | null;
    if (!p || p.kind !== "via" || !p.name) continue;
    const g = f.geometry;
    const linhas: number[][][] =
      g.type === "LineString"
        ? [g.coordinates as number[][]]
        : g.type === "MultiLineString"
          ? (g.coordinates as number[][][])
          : [];
    for (const linha of linhas) {
      if (linha.length < 2) continue;
      const a = rotas.celula(linha[0][0], linha[0][1]);
      const b = rotas.celula(linha[linha.length - 1][0], linha[linha.length - 1][1]);
      out.push({
        nome: String(p.name),
        derivado: p.nome_derivado === true,
        a,
        b,
        largura: typeof p.largura_m === "number" ? p.largura_m : 4,
      });
    }
  }
  return out;
}

function anguloEntre(u: [number, number], v: [number, number]): number {
  const cos = (u[0] * v[0] + u[1] * v[1]) / (Math.hypot(...u) * Math.hypot(...v) || 1);
  return (Math.acos(Math.max(-1, Math.min(1, cos))) * 180) / Math.PI;
}

/** distância de um ponto ao segmento, em unidades de célula */
function aoSegmento(p: [number, number], a: [number, number], b: [number, number]): number {
  const vx = b[0] - a[0];
  const vy = b[1] - a[1];
  const n = vx * vx + vy * vy;
  const t = n ? Math.max(0, Math.min(1, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / n)) : 0;
  return Math.hypot(p[0] - (a[0] + t * vx), p[1] - (a[1] + t * vy));
}

/** fração do trecho que corre dentro da faixa da via */
function cobertura(
  a: [number, number],
  b: [number, number],
  v: Via,
  passo: number,
): number {
  const faixa = v.largura / 2 + FOLGA_M;
  let dentro = 0;
  for (let i = 0; i <= AMOSTRAS; i++) {
    const t = i / AMOSTRAS;
    const p: [number, number] = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    if (aoSegmento(p, v.a, v.b) * passo <= faixa) dentro++;
  }
  return dentro / (AMOSTRAS + 1);
}

/**
 * Via que melhor explica um trecho, ou null.
 *
 * Ganha a via que cobre a maior parte do trecho, desde que cubra o bastante.
 * Empate é desempatado pela mais larga, que é a que tem placa.
 */
function viaDoTrecho(
  a: [number, number],
  b: [number, number],
  vias: Via[],
  passo: number,
): Via | null {
  let melhor: Via | null = null;
  let cmax = 0;
  for (const v of vias) {
    const c = cobertura(a, b, v, passo);
    if (c > cmax + 1e-9 || (Math.abs(c - cmax) <= 1e-9 && melhor && v.largura > melhor.largura)) {
      cmax = Math.max(c, cmax);
      melhor = v;
    }
  }
  return cmax >= COBERTURA_MIN ? melhor : null;
}

/**
 * Distância do passo, em passos de 5 m.
 *
 * Não é para parecer preciso: ninguém conta metro andando. É para não
 * contradizer o total do trecho, que aparece logo acima e é exato — arredondar
 * de 10 em 10 fazia "66 m" virar "siga 70 m" na mesma tela.
 */
function arredonda(m: number): number {
  return Math.max(5, Math.round(m / 5) * 5);
}

/**
 * Traçado enxuto -> lista de passos.
 *
 * O traçado já vem sem serrilha (Rotas.enxuga), então cada vértice é uma curva
 * de verdade. Aqui os trechos consecutivos que correm pela mesma via são
 * fundidos: sem isso, um corredor com um leve desvio para contornar uma quina
 * viraria três instruções para a mesma rua.
 */
export function instrucoes(
  cels: [number, number][],
  vias: Via[],
  rotas: Rotas,
  destino?: string,
): Passo[] {
  const passo = rotas.passo;
  const mao = rotas.orientacao();
  if (cels.length < 2) return [];

  // 1. trechos crus, cada um com a via que o explica. `dir` fica guardado
  //    separado porque a fusão muda os extremos do trecho mas a manobra tem
  //    que continuar sendo julgada pela direção da parte que vale
  type Trecho = {
    a: [number, number];
    b: [number, number];
    dir: [number, number];
    via: Via | null;
    m: number;
  };
  const trechos: Trecho[] = [];
  for (let k = 1; k < cels.length; k++) {
    const a = cels[k - 1];
    const b = cels[k];
    const m = Math.hypot(b[0] - a[0], b[1] - a[1]) * passo;
    trechos.push({ a, b, dir: [b[0] - a[0], b[1] - a[1]], via: viaDoTrecho(a, b, vias, passo), m });
  }

  // 2. funde trechos vizinhos que correm pela mesma via: um corredor com um
  //    leve desvio para contornar quina viraria três instruções para a mesma rua
  const mesmaVia: Trecho[] = [];
  for (const t of trechos) {
    const ant = mesmaVia[mesmaVia.length - 1];
    if (ant && ant.via && t.via && ant.via.nome === t.via.nome) {
      ant.b = t.b;
      ant.m += t.m;
      if (t.m > ant.m / 2) ant.dir = t.dir;
    } else {
      mesmaVia.push({ ...t });
    }
  }

  // 3. absorve os pedaços curtos sem nome. Trocar de rua num pavilhão custa
  //    uns metros de diagonal pela boca da transversal, e o A* devolve isso
  //    como trecho próprio — mas ninguém diz "vire à direita, ande 8 metros,
  //    vire à esquerda": diz "entre na Rua H". O pedaço pertence à manobra de
  //    entrar na via seguinte, então é fundido PARA FRENTE; no fim da rota,
  //    onde não há via seguinte, ele é a aproximação do destino e vai para trás.
  const juntos: Trecho[] = [];
  for (let k = 0; k < mesmaVia.length; k++) {
    const t = mesmaVia[k];
    const curto = !t.via && t.m < CURTO_M;
    const prox = mesmaVia[k + 1];
    if (curto && prox) {
      prox.a = t.a;
      prox.m += t.m;
      continue;
    }
    const ant = juntos[juntos.length - 1];
    if (curto && ant) {
      ant.b = t.b;
      ant.m += t.m;
      continue;
    }
    juntos.push(t);
  }

  // 3. vira texto
  const out: Passo[] = [];
  for (let k = 0; k < juntos.length; k++) {
    const t = juntos[k];
    const dist = arredonda(t.m);
    let virar: Passo["virar"] = "frente";
    if (k === 0) {
      virar = "partida";
    } else {
      const u = juntos[k - 1].dir;
      const v = t.dir;
      const ang = anguloEntre(u, v);
      if (ang >= VIRADA_MIN) {
        // o produto vetorial dá o sentido do giro em coordenadas de célula;
        // `mao` traduz isso para o mundo, porque o frame da malha é espelhado
        // em relação a (leste, norte) e sem a correção a instrução sai trocada
        virar = (u[0] * v[1] - u[1] * v[0]) * mao > 0 ? "esquerda" : "direita";
      }
    }
    const onde = t.via ? ` pela ${t.via.nome}` : "";
    // ruas paralelas se emendam por uma boca de poucos metros, que a fusão
    // engoliu: o rumo não muda, mas a rua sim, e dizer "continue" ali faria a
    // pessoa passar direto. "Passe para" é o que descreve o gesto.
    const trocou = virar === "frente" && t.via && t.via.nome !== juntos[k - 1]?.via?.nome;
    const texto =
      virar === "partida"
        ? t.via
          ? `Siga pela ${t.via.nome} por ${dist} m`
          : `Siga em frente por ${dist} m`
        : trocou
          ? `Passe para a ${t.via!.nome} e siga ${dist} m`
          : virar === "frente"
            ? `Continue${onde || " em frente"} por ${dist} m`
            : `Vire à ${virar}${onde} e siga ${dist} m`;
    out.push({ virar, via: t.via?.nome ?? null, derivado: t.via?.derivado ?? false, metros: t.m, texto });
  }

  out.push({
    virar: "chegada",
    via: null,
    derivado: false,
    metros: 0,
    texto: destino ? `Chegou: ${destino}` : "Chegou ao destino",
  });
  return out;
}
