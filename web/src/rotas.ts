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

  get passo(): number {
    return this.m.passo;
  }

  /** extensão da grade em metros — serve de régua para limites que não devem ser chutados */
  extensao(): [number, number] {
    return [this.m.w * this.m.passo, this.m.h * this.m.passo];
  }

  /**
   * lng/lat -> célula fracionária, invertendo a afim do build.
   *
   * A afim é [ex ey] aplicada em (i,j); aqui resolvemos o sistema 2x2. Sai
   * fracionário de propósito: quem chama decide se arredonda (posição de
   * toque) ou se usa a fração para medir distância em metros.
   */
  celula(lng: number, lat: number): [number, number] {
    const { origem, ex, ey } = this.m;
    const dx = lng - origem[0];
    const dy = lat - origem[1];
    const det = ex[0] * ey[1] - ey[0] * ex[1];
    return [(dx * ey[1] - ey[0] * dy) / det, (ex[0] * dy - dx * ex[1]) / det];
  }

  livreEm(i: number, j: number): boolean {
    const { w, h } = this.m;
    if (i < 0 || j < 0 || i >= w || j >= h) return false;
    return this.livre[j * w + i] === 1;
  }

  /**
   * Célula livre mais próxima de um ponto, por anéis crescentes.
   *
   * Toque de dedo num celular cai em cima de estande na maior parte das
   * vezes, e GPS de pavilhão cai em qualquer lugar. Sem esta função a rota
   * simplesmente não nasce e o app parece quebrado. `limite` em metros evita
   * arrastar um ponto do estacionamento para dentro do salão.
   */
  maisProximaLivre(lng: number, lat: number, limite = 25): [number, number] | null {
    const [fi, fj] = this.celula(lng, lat);
    const ci = Math.round(fi);
    const cj = Math.round(fj);
    if (this.livreEm(ci, cj)) return [ci, cj];
    const raio = Math.ceil(limite / this.m.passo);
    for (let r = 1; r <= raio; r++) {
      let melhor: [number, number] | null = null;
      let dist = Infinity;
      for (let d = -r; d <= r; d++) {
        for (const [i, j] of [
          [ci + d, cj - r],
          [ci + d, cj + r],
          [ci - r, cj + d],
          [ci + r, cj + d],
        ] as [number, number][]) {
          if (!this.livreEm(i, j)) continue;
          const s = (i - fi) ** 2 + (j - fj) ** 2;
          if (s < dist) {
            dist = s;
            melhor = [i, j];
          }
        }
      }
      if (melhor) return melhor;
    }
    return null;
  }

  /** distância em linha reta, em metros, entre duas células (aceita fracionárias) */
  distancia(a: [number, number], b: [number, number]): number {
    return Math.hypot(a[0] - b[0], a[1] - b[1]) * this.m.passo;
  }

  /**
   * Rota entre dois pontos quaisquer — é este o caminho principal do app.
   *
   * O evento é indoor: GPS erra de 10 a 50 m e o corredor tem 3 m, então a
   * posição do visitante não vem de sensor, vem de ele apontar onde está.
   * Origem e destino são simétricos por isso.
   */
  rota(de: [number, number], ate: [number, number]): { cels: [number, number][]; metros: number } | null {
    const cels = this.caminho(de, ate);
    if (!cels) return null;
    // o comprimento é medido no traçado já enxuto: a escada de células de
    // 0,5 m do A* infla a distância em ~8%, e é o traçado reto que a pessoa
    // efetivamente anda
    const enxuto = this.enxuga(cels);
    return { cels: enxuto, metros: this.metros(enxuto) };
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
    cel: [number, number];
    cels: [number, number][];
    metros: number;
  } | null {
    let melhor: { porta: string; cel: [number, number]; cels: [number, number][]; metros: number } | null = null;
    for (const { nome, cel } of this.portas()) {
      const r = this.rota(cel, destino);
      if (!r) continue;
      if (!melhor || r.metros < melhor.metros) melhor = { porta: nome, cel, ...r };
    }
    return melhor;
  }
}
