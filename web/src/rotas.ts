/**
 * Rota dentro do pavilhão: A* sobre a malha de células livres.
 *
 * Roda no navegador de propósito. A origem de uma rota é o visitante, e ela
 * muda a cada passo — pré-calcular caminho não serviria. A malha inteira cabe
 * em ~34 KB, então o custo de ter isso offline é baixo.
 *
 * A malha vem de tools/build_route.py: bitmask das células caminháveis mais o
 * ponto de acesso de cada estande.
 */

export interface Malha {
  passo: number;
  w: number;
  h: number;
  origem: [number, number];
  ex: [number, number];
  ey: [number, number];
  livre: string;
  acessos: Record<string, [number, number]>;
  portas: Record<string, [number, number][]>;
}

export class Rotas {
  private livre: Uint8Array;
  private m: Malha;

  constructor(m: Malha) {
    this.m = m;
    const bin = atob(m.livre);
    this.livre = new Uint8Array(m.w * m.h);
    for (let k = 0; k < this.livre.length; k++) {
      this.livre[k] = (bin.charCodeAt(k >> 3) >> (7 - (k & 7))) & 1;
    }
  }

  /** célula -> lng/lat, pela afim que o build gravou */
  lngLat([i, j]: [number, number]): [number, number] {
    const { origem, ex, ey } = this.m;
    return [origem[0] + i * ex[0] + j * ey[0], origem[1] + i * ex[1] + j * ey[1]];
  }

  acesso(chave: string): [number, number] | undefined {
    return this.m.acessos[chave];
  }

  /** todas as portas do evento, achatadas */
  portas(): { nome: string; cel: [number, number] }[] {
    return Object.entries(this.m.portas).flatMap(([nome, cels]) =>
      cels.map((cel) => ({ nome, cel })),
    );
  }

  /**
   * A* 8-vizinhos com heurística octile (admissível para esta vizinhança:
   * nunca superestima, então o caminho sai ótimo).
   *
   * Diagonal só passa se os dois ortogonais também estiverem livres — sem
   * isso a rota corta a quina do estande e atravessa parede.
   */
  caminho(de: [number, number], ate: [number, number]): [number, number][] | null {
    const { w, h } = this.m;
    const idx = (i: number, j: number) => j * w + i;
    const inicio = idx(de[0], de[1]);
    const fim = idx(ate[0], ate[1]);
    if (!this.livre[inicio] || !this.livre[fim]) return null;

    const N = w * h;
    const g = new Float32Array(N).fill(Infinity);
    const veio = new Int32Array(N).fill(-1);
    const fechado = new Uint8Array(N);
    const D = Math.SQRT2 - 1;
    const heur = (c: number) => {
      const dx = Math.abs((c % w) - ate[0]);
      const dy = Math.abs(Math.floor(c / w) - ate[1]);
      return Math.max(dx, dy) + D * Math.min(dx, dy);
    };

    // heap binário: com ~76 mil células, fila ordenada por varredura linear
    // deixaria a busca visivelmente lenta no celular
    const heap: number[] = [];
    const custo = new Float32Array(N);
    const sobe = (k: number) => {
      while (k > 0) {
        const p = (k - 1) >> 1;
        if (custo[heap[p]] <= custo[heap[k]]) break;
        [heap[p], heap[k]] = [heap[k], heap[p]];
        k = p;
      }
    };
    const desce = (k: number) => {
      for (;;) {
        const l = 2 * k + 1;
        if (l >= heap.length) break;
        const r = l + 1;
        const m = r < heap.length && custo[heap[r]] < custo[heap[l]] ? r : l;
        if (custo[heap[k]] <= custo[heap[m]]) break;
        [heap[m], heap[k]] = [heap[k], heap[m]];
        k = m;
      }
    };

    g[inicio] = 0;
    custo[inicio] = heur(inicio);
    heap.push(inicio);

    while (heap.length) {
      const atual = heap[0];
      heap[0] = heap[heap.length - 1];
      heap.pop();
      if (heap.length) desce(0);
      if (atual === fim) break;
      if (fechado[atual]) continue;
      fechado[atual] = 1;

      const ci = atual % w;
      const cj = Math.floor(atual / w);
      for (let dj = -1; dj <= 1; dj++) {
        for (let di = -1; di <= 1; di++) {
          if (!di && !dj) continue;
          const ni = ci + di;
          const nj = cj + dj;
          if (ni < 0 || ni >= w || nj < 0 || nj >= h) continue;
          const n = idx(ni, nj);
          if (!this.livre[n] || fechado[n]) continue;
          if (di && dj && !(this.livre[idx(ni, cj)] && this.livre[idx(ci, nj)])) continue;
          const passo = di && dj ? Math.SQRT2 : 1;
          const alt = g[atual] + passo;
          if (alt < g[n]) {
            g[n] = alt;
            veio[n] = atual;
            custo[n] = alt + heur(n);
            heap.push(n);
            sobe(heap.length - 1);
          }
        }
      }
    }

    if (!isFinite(g[fim])) return null;
    const cels: [number, number][] = [];
    for (let c = fim; c !== -1; c = veio[c]) cels.push([c % w, Math.floor(c / w)]);
    return cels.reverse();
  }

  /**
   * Enxuga o caminho: mantém só os pontos onde a rota realmente vira.
   *
   * O A* devolve uma escada de células de 0,5 m; desenhar isso dá um traço
   * serrilhado e um "vire à esquerda" a cada meio metro. Aqui é feita a
   * varredura de visibilidade — se dá para ir direto do ponto fixo até o
   * candidato sem sair da área livre, o meio do caminho não é curva.
   */
  enxuga(cels: [number, number][]): [number, number][] {
    if (cels.length < 3) return cels;
    const out: [number, number][] = [cels[0]];
    let ancora = 0;
    for (let k = 2; k < cels.length; k++) {
      if (!this.visivel(cels[ancora], cels[k])) {
        out.push(cels[k - 1]);
        ancora = k - 1;
      }
    }
    out.push(cels[cels.length - 1]);
    return out;
  }

  /** linha reta entre duas células passa só por células livres? */
  private visivel(a: [number, number], b: [number, number]): boolean {
    const n = Math.max(Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]));
    if (!n) return true;
    for (let s = 0; s <= n; s++) {
      const i = Math.round(a[0] + ((b[0] - a[0]) * s) / n);
      const j = Math.round(a[1] + ((b[1] - a[1]) * s) / n);
      if (!this.livre[j * this.m.w + i]) return false;
    }
    return true;
  }

  /** comprimento em metros de um caminho de células */
  metros(cels: [number, number][]): number {
    let d = 0;
    for (let k = 1; k < cels.length; k++) {
      d += Math.hypot(cels[k][0] - cels[k - 1][0], cels[k][1] - cels[k - 1][1]);
    }
    return d * this.m.passo;
  }

  /** rota da porta mais conveniente até um destino, escolhendo pela distância real */
  daPortaMaisProxima(destino: [number, number]): {
    porta: string;
    cels: [number, number][];
    metros: number;
  } | null {
    let melhor: { porta: string; cels: [number, number][]; metros: number } | null = null;
    for (const { nome, cel } of this.portas()) {
      const cels = this.caminho(cel, destino);
      if (!cels) continue;
      const m = this.metros(cels);
      if (!melhor || m < melhor.metros) melhor = { porta: nome, cels, metros: m };
    }
    return melhor;
  }
}
