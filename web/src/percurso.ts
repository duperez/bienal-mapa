/**
 * Percurso: uma lista ordenada de paradas e o caminho que passa por todas.
 *
 * O evento é indoor, sob telhado metálico, e o navegador devolve fixes de 10 a
 * 50 m num pavilhão cujo corredor mais largo tem 7 m. Posição errada aponta a
 * direção errada com toda a confiança do mundo, então aqui o visitante APONTA
 * onde está — por busca (o código do estande é a placa que ele tem diante dos
 * olhos) ou por toque no mapa. Não há GPS neste arquivo, de propósito.
 *
 * O ganho estrutural disso é grande: com todos os pontos escolhidos sobre o
 * desenho, o erro de georreferência do desenho dentro do prédio (defeitos 4 e
 * 8) se cancela. A rota é exata mesmo com a âncora errada, porque origem,
 * paradas e destino vivem no mesmo sistema de coordenadas do traçado.
 *
 * Por que lista e não par origem/destino: numa Bienal ninguém vai a um lugar
 * só. O caso real é "quero passar na Companhia das Letras, na Intrínseca e
 * depois no banheiro" — e a ordem em que se faz isso muda bastante a distância
 * andada. Daí `otimizar()`.
 */

import type { Rotas } from "./rotas";
import type { Passo } from "./instrucoes";

export interface Ponto {
  rotulo: string;
  cel: [number, number];
}

export interface Contexto {
  rotas: Rotas;
  /** um traçado por trecho entre paradas consecutivas */
  desenhaRota(trechos: [number, number][][]): void;
  /** marcadores das paradas, na ordem (posições vazias entram como null) */
  desenhaPontos(paradas: (Ponto | null)[]): void;
  enquadra(cels: [number, number][]): void;
  /** avisa o app que o próximo toque/busca preenche esta parada */
  aoEscolher(indice: number | null): void;
  /** passos falados de um trecho; o app injeta porque as vias vêm do geojson */
  instrucoes(cels: [number, number][], destino: string): Passo[];
}

const LEMBRETE = "bienal.percurso";
/**
 * Teto de paradas. Não é limite técnico — `otimizar()` aguenta mais — é limite
 * de tela e de utilidade: um roteiro de dez pontos numa feira lotada não
 * sobrevive ao primeiro imprevisto.
 */
const MAX_PARADAS = 8;
/** acima disto a busca exaustiva da melhor ordem sai cara; abaixo é instantânea */
const EXAUSTIVO_ATE = 7;
/** passo de gente andando em feira cheia, olhando para os lados: ~1,25 m/s */
const M_POR_MIN = 75;

type Trecho = { cels: [number, number][]; metros: number } | null;

export class Percurso {
  private ctx: Contexto;
  private el: HTMLElement;
  /** sempre com pelo menos duas posições; `null` é posição ainda não escolhida */
  private paradas: (Ponto | null)[] = [null, null];
  private escolha: number | null = null;
  /** trechos com a lista de passos aberta; fechado por padrão para a tela caber */
  private abertos = new Set<number>();

  constructor(ctx: Contexto) {
    this.ctx = ctx;
    this.el = document.createElement("div");
    this.el.id = "rota";
    this.el.innerHTML = `
      <div id="rotaCab">
        <div id="rotaTitulo">Seu percurso</div>
        <div id="rotaTotal"></div>
      </div>
      <div id="rotaParadas"></div>
      <div id="rotaAviso"></div>
      <div id="rotaBarra">
        <button id="rotaAdd" type="button">+ Parada</button>
        <button id="rotaOtimiza" type="button">Melhor ordem</button>
        <button id="rotaInverte" type="button" aria-label="Inverter a ordem">⇅</button>
        <button id="rotaFechar" type="button">Fechar</button>
      </div>`;
    document.body.appendChild(this.el);

    this.$("rotaAdd").addEventListener("click", () => this.adicionar());
    this.$("rotaOtimiza").addEventListener("click", () => this.otimizar());
    this.$("rotaInverte").addEventListener("click", () => this.inverter());
    this.$("rotaFechar").addEventListener("click", () => this.fechar());
    this.$("rotaParadas").addEventListener("click", (e) => this.clique(e));
  }

  private $(id: string): HTMLElement {
    return this.el.querySelector(`#${id}`) as HTMLElement;
  }

  get aberto(): boolean {
    return this.el.classList.contains("open");
  }

  /** índice da parada em escolha; `null` quando nenhum campo espera um toque */
  get escolhendo(): number | null {
    return this.escolha;
  }

  /** quantas paradas já têm lugar definido */
  get preenchidas(): number {
    return this.paradas.filter(Boolean).length;
  }

  // ------------------------------------------------------------ ciclo de vida

  /**
   * Entrada pelo botão da ficha de um lugar.
   *
   * Fechado, monta o par comum: destino escolhido e origem pré-preenchida com
   * a última usada ou a porta mais próxima — sempre escrita na tela, para o
   * app nunca rotear de um lugar que o visitante não escolheu sem perceber.
   *
   * Já aberto, o lugar entra como nova parada FINAL. É o gesto natural de
   * quem monta roteiro: procura, adiciona, procura de novo. O que era destino
   * vira parada do meio sozinho.
   */
  abrir(p: Ponto): void {
    if (this.aberto && this.preenchidas >= 2) {
      this.anexar(p);
      return;
    }
    if (this.paradas.length === 2 && !this.paradas[1]) {
      this.paradas[1] = p;
      if (!this.paradas[0]) this.paradas[0] = this.lembrada() ?? this.portaPara(p);
      this.escolha = null;
      this.ctx.aoEscolher(null);
      this.el.classList.add("open");
      this.atualiza();
    } else {
      this.anexar(p);
    }
  }

  fechar(): void {
    this.el.classList.remove("open");
    this.escolha = null;
    this.ctx.aoEscolher(null);
    this.ctx.desenhaRota([]);
    this.ctx.desenhaPontos([]);
  }

  /** preenche a parada em escolha (ou a primeira vaga) e recalcula */
  define(p: Ponto): void {
    const i = this.escolha ?? this.paradas.findIndex((x) => !x);
    if (i < 0) {
      this.anexar(p);
      return;
    }
    this.paradas[i] = p;
    this.escolha = null;
    this.ctx.aoEscolher(null);
    if (!this.aberto) this.el.classList.add("open");
    this.atualiza();
  }

  // --------------------------------------------------------------- comandos

  private anexar(p: Ponto): void {
    if (this.paradas.length >= MAX_PARADAS) {
      // substituir o fim é menos ruim que ignorar o toque em silêncio
      this.paradas[this.paradas.length - 1] = p;
    } else {
      this.paradas.push(p);
    }
    this.escolha = null;
    this.ctx.aoEscolher(null);
    if (!this.aberto) this.el.classList.add("open");
    this.atualiza();
  }

  private adicionar(): void {
    if (this.paradas.length >= MAX_PARADAS) return;
    this.paradas.push(null);
    this.escolher(this.paradas.length - 1);
  }

  private escolher(i: number): void {
    this.escolha = this.escolha === i ? null : i;
    this.ctx.aoEscolher(this.escolha);
    this.atualiza();
  }

  private remover(i: number): void {
    if (this.paradas.length > 2) this.paradas.splice(i, 1);
    else this.paradas[i] = null;
    if (this.escolha !== null && this.escolha >= this.paradas.length) this.escolha = null;
    else if (this.escolha === i) this.escolha = null;
    this.ctx.aoEscolher(this.escolha);
    this.atualiza();
  }

  private mover(i: number, passo: number): void {
    const j = i + passo;
    if (j < 0 || j >= this.paradas.length) return;
    const t = this.paradas[i];
    this.paradas[i] = this.paradas[j];
    this.paradas[j] = t;
    this.escolha = null;
    this.ctx.aoEscolher(null);
    this.atualiza();
  }

  private inverter(): void {
    this.paradas.reverse();
    this.escolha = null;
    this.ctx.aoEscolher(null);
    this.atualiza();
  }

  /**
   * Reordena as paradas do meio para andar menos, com origem e destino presos.
   *
   * Presos porque são as duas que o visitante escolheu por um motivo: de onde
   * está e onde quer terminar. Trocá-las seria o app decidindo o passeio dele.
   *
   * A distância entre pares é a do A* sobre a malha, não a linha reta: num
   * pavilhão com fileiras de estandes duas coisas a 10 m uma da outra podem
   * ficar a 80 m de caminhada, e é a caminhada que dói no pé.
   */
  private otimizar(): void {
    const pts = this.paradas;
    if (pts.length < 4 || pts.some((p) => !p)) return;
    const cheio = pts as Ponto[];
    const n = cheio.length;

    const d: number[][] = Array.from({ length: n }, () => new Array<number>(n).fill(Infinity));
    for (let i = 0; i < n; i++) {
      d[i][i] = 0;
      for (let j = i + 1; j < n; j++) {
        const r = this.ctx.rotas.rota(cheio[i].cel, cheio[j].cel);
        d[i][j] = d[j][i] = r ? r.metros : Infinity;
      }
    }

    const meio = Array.from({ length: n - 2 }, (_, k) => k + 1);
    const custo = (ordem: number[]): number => {
      let t = 0;
      let a = 0;
      for (const b of ordem) {
        t += d[a][b];
        a = b;
      }
      return t + d[a][n - 1];
    };

    const melhor = meio.length <= EXAUSTIVO_ATE ? exaustivo(meio, custo) : doisOpt(meio, custo);
    const antes = custo(meio);
    const depois = custo(melhor);
    if (!(depois < antes - 0.5)) {
      this.avisa("Esta já é a melhor ordem");
      return;
    }
    this.paradas = [cheio[0], ...melhor.map((k) => cheio[k]), cheio[n - 1]];
    this.atualiza();
    this.avisa(`Ordem trocada: ${Math.round(antes - depois)} m a menos`);
  }

  // ----------------------------------------------------------------- eventos

  private clique(e: Event): void {
    const b = (e.target as HTMLElement).closest<HTMLElement>("button[data-acao]");
    if (!b) return;
    const linha = b.closest<HTMLElement>("[data-i]");
    if (!linha) return;
    const i = Number(linha.dataset.i);
    const acao = b.dataset.acao;
    if (acao === "escolher") this.escolher(i);
    else if (acao === "remove") this.remover(i);
    else if (acao === "passos") this.alternaPassos(i);
    else if (acao === "sobe") this.mover(i, -1);
    else if (acao === "desce") this.mover(i, 1);
  }

  // ------------------------------------------------------------------ desenho

  /**
   * `enquadrar=false` para mudanças que não mexem no traçado (abrir os passos
   * de um trecho): reenquadrar o mapa ali roubaria o zoom de quem está lendo.
   */
  private atualiza(enquadrar = true): void {
    const n = this.paradas.length;
    const trechos: Trecho[] = [];
    for (let i = 0; i + 1 < n; i++) {
      const a = this.paradas[i];
      const b = this.paradas[i + 1];
      trechos.push(a && b ? this.ctx.rotas.rota(a.cel, b.cel) : null);
    }

    this.$("rotaParadas").innerHTML = this.paradas
      .map((p, i) => this.linha(p, i, n, i > 0 ? trechos[i - 1] : undefined))
      .join("");

    this.ctx.desenhaPontos(this.paradas);
    this.$("rotaAdd").toggleAttribute("disabled", n >= MAX_PARADAS);
    this.$("rotaOtimiza").hidden = n < 4;

    const feitos = trechos.filter((t): t is NonNullable<Trecho> => !!t);
    this.ctx.desenhaRota(feitos.map((t) => t.cels));

    const total = this.$("rotaTotal");
    if (!this.paradas.every(Boolean)) {
      total.textContent = "";
      this.dica();
      return;
    }
    if (feitos.length < trechos.length) {
      total.textContent = "";
      this.avisa("Não há caminho entre duas das paradas");
      return;
    }
    const metros = feitos.reduce((s, t) => s + t.metros, 0);
    total.textContent =
      `${Math.round(metros)} m · ${Math.max(1, Math.round(metros / M_POR_MIN))} min a pé`;
    this.avisa("");
    this.lembra();
    if (enquadrar) this.ctx.enquadra(feitos.flatMap((t) => t.cels));
  }

  private alternaPassos(i: number): void {
    if (this.abertos.has(i)) this.abertos.delete(i);
    else this.abertos.add(i);
    this.atualiza(false);
  }

    /**
   * Passos falados de um trecho.
   *
   * Ficam recolhidos porque a lista de paradas é o que se consulta o tempo
   * todo e os passos só na hora de andar; abrir tudo empurraria o roteiro para
   * fora da tela do celular. Rua com nome derivado sai marcada — o visitante
   * não vai achar essa placa pendurada no corredor.
   */
  private passos(i: number, antes: NonNullable<Trecho>): string {
    if (!this.abertos.has(i)) return "";
    const destino = this.paradas[i]?.rotulo ?? "destino";
    const lista = this.ctx.instrucoes(antes.cels, destino);
    if (!lista.length) return "";
    return `<ol class="rota-passos">${lista
      .map(
        (s) =>
          `<li class="rota-passo passo-${s.virar}">${escapa(s.texto)}` +
          (s.derivado ? '<span class="rota-derivado" title="nome derivado: o PDF numera mas não rotula esta via">~</span>' : "") +
          `</li>`,
      )
      .join("")}</ol>`;
  }

  private linha(p: Ponto | null, i: number, n: number, antes?: Trecho): string {
    // o comprimento do trecho anterior fica ENTRE as duas paradas, que é onde
    // a pergunta nasce: "quanto tem daqui até a próxima?"
    const emenda =
      i > 0
        ? `<div class="rota-emenda" data-i="${i}">` +
          (antes
            ? `<button class="rota-mais" type="button" data-acao="passos"` +
              ` aria-expanded="${this.abertos.has(i)}">` +
              `${Math.round(antes.metros)} m` +
              `<span class="rota-seta">${this.abertos.has(i) ? "▾" : "▸"}</span></button>` +
              this.passos(i, antes)
            : "—") +
          `</div>`
        : "";
    const papel = i === 0 ? "origem" : i === n - 1 ? "destino" : "parada";
    const vazio = i === 0 ? "Onde você está?" : i === n - 1 ? "Para onde vai?" : "Passar por…";
    const classe = `rota-campo${p ? "" : " vazio"}${this.escolha === i ? " ativo" : ""}`;
    return `${emenda}
      <div class="rota-linha" data-i="${i}">
        <button class="${classe}" type="button" data-acao="escolher">
          <span class="rota-marca rota-marca-${papel}">${letra(i)}</span>
          <span class="rota-texto">${escapa(p ? p.rotulo : vazio)}</span>
        </button>
        <div class="rota-acoes">
          <button type="button" data-acao="sobe" aria-label="Subir" ${i === 0 ? "disabled" : ""}>↑</button>
          <button type="button" data-acao="desce" aria-label="Descer" ${i === n - 1 ? "disabled" : ""}>↓</button>
          <button type="button" data-acao="remove" aria-label="Remover">×</button>
        </div>
      </div>`;
  }

  private dica(): void {
    if (this.escolha === null) {
      this.avisa("Toque num campo para escolher o lugar");
      return;
    }
    const n = this.paradas.length;
    this.avisa(
      this.escolha === 0
        ? "Busque ou toque no mapa onde você está"
        : this.escolha === n - 1
          ? "Busque ou toque no mapa aonde quer ir"
          : "Busque ou toque no mapa por onde quer passar",
    );
  }

  private avisa(texto: string): void {
    this.$("rotaAviso").textContent = texto;
  }

  // ------------------------------------------------------- roteiro lembrado

  private lembra(): void {
    try {
      localStorage.setItem(LEMBRETE, JSON.stringify(this.paradas));
    } catch {
      /* modo privado: seguir sem lembrar é aceitável */
    }
  }

  /** só devolve o que ainda existe: a malha muda a cada build */
  private lembrada(): Ponto | null {
    try {
      const cru = localStorage.getItem(LEMBRETE);
      if (!cru) return null;
      const ps = JSON.parse(cru) as (Ponto | null)[];
      const p = ps?.[0];
      if (!p?.cel || !this.ctx.rotas.livreEm(p.cel[0], p.cel[1])) return null;
      return p;
    } catch {
      return null;
    }
  }

  private portaPara(destino: Ponto): Ponto | null {
    const r = this.ctx.rotas.daPortaMaisProxima(destino.cel);
    return r ? { rotulo: r.porta, cel: r.cel } : null;
  }
}

// --------------------------------------------------------------- utilitários

function letra(i: number): string {
  return String.fromCharCode(65 + (i % 26));
}

/** todas as permutações: exato, e para até 7 paradas do meio é instantâneo */
function exaustivo(base: number[], custo: (o: number[]) => number): number[] {
  let melhor = base;
  let menor = custo(base);
  const perm = (resto: number[], atual: number[]): void => {
    if (!resto.length) {
      const c = custo(atual);
      if (c < menor) {
        menor = c;
        melhor = atual;
      }
      return;
    }
    for (let k = 0; k < resto.length; k++) {
      perm([...resto.slice(0, k), ...resto.slice(k + 1)], [...atual, resto[k]]);
    }
  };
  perm(base, []);
  return melhor;
}

/** inversão de trechos até não melhorar mais: aproximado, para listas grandes */
function doisOpt(base: number[], custo: (o: number[]) => number): number[] {
  let melhor = [...base];
  let menor = custo(melhor);
  let mudou = true;
  while (mudou) {
    mudou = false;
    for (let i = 0; i < melhor.length - 1; i++) {
      for (let j = i + 1; j < melhor.length; j++) {
        const alt = [
          ...melhor.slice(0, i),
          ...melhor.slice(i, j + 1).reverse(),
          ...melhor.slice(j + 1),
        ];
        const c = custo(alt);
        if (c < menor - 1e-9) {
          melhor = alt;
          menor = c;
          mudou = true;
        }
      }
    }
  }
  return melhor;
}

function escapa(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
}
