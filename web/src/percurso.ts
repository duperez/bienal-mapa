/**
 * Percurso: escolher origem e destino e ver a rota entre eles.
 *
 * A regra do projeto é que o GPS não manda. O evento é indoor, sob telhado
 * metálico: o navegador devolve fixes com 10 a 50 m de erro, e o corredor
 * mais largo do pavilhão tem 7 m. Uma posição errada apontaria a direção
 * errada com toda a confiança do mundo — pior do que não ter posição.
 *
 * Então o visitante APONTA onde está (busca ou toque no mapa) e o GPS entra
 * só como camada opcional, e mesmo assim para ORDENAR candidatos, nunca para
 * filtrar. O motivo de ordenar em vez de filtrar é o defeito nº 4: a âncora
 * do desenho dentro do prédio ainda é palpite com ~30 m de folga em x e ~75 m
 * em y. Um raio desenhado a partir do GPS sairia descentrado por mais do que
 * o próprio erro do sensor e poderia excluir justamente o estande certo.
 * Ordenando, o erro de âncora piora a ordem da lista e nunca esconde a
 * resposta.
 */

import type { Rotas } from "./rotas";
import { posicao, simulando } from "./gps";

export interface Ponto {
  rotulo: string;
  cel: [number, number];
}

export interface Contexto {
  rotas: Rotas;
  /** traçado da rota (null limpa) */
  desenhaRota(cels: [number, number][] | null): void;
  /** marcadores de origem e destino */
  desenhaPontos(origem: Ponto | null, destino: Ponto | null): void;
  /** círculo de incerteza do GPS, em metros (null limpa) */
  desenhaIncerteza(cel: [number, number] | null, raio: number): void;
  enquadra(cels: [number, number][]): void;
  /**
   * Locais roteáveis dentro de um raio, ordenados por distância.
   *
   * O raio vem do `accuracy` do fix, então a lista encolhe quando o sinal é
   * bom e cresce quando é ruim — que é a informação honesta a dar. `min`
   * garante que uma leitura muito precisa ainda ofereça alternativa, e `max`
   * impede a lista de virar o índice inteiro.
   */
  candidatos(cel: [number, number], raio: number, min: number, max: number): Ponto[];
  /** avisa o app que o próximo toque/busca preenche este campo */
  aoEscolher(campo: Campo | null): void;
}

export type Campo = "origem" | "destino";

const LEMBRETE = "bienal.origem";
/** fix pendurado é o desfecho mais comum indoor; não dá para travar a tela */
const ESPERA_MS = 6000;
/**
 * Precisão a partir da qual não vale seguir esperando: metade da menor rua do
 * mapa (LARG_MIN = 2 m) seria fantasia indoor, então o critério é o vão entre
 * fileiras — com ±12 m o círculo já cabe em poucas fileiras e a lista é curta.
 */
const BOM_M = 12;
/** quanto esperar por um fix melhor depois que o primeiro chegou */
const ASSENTA_MS = 1500;
/** a lista de candidatos precisa caber na tela e ainda dar escolha */
const MIN_OPCOES = 3;
const MAX_OPCOES = 12;

export class Percurso {
  private ctx: Contexto;
  private el: HTMLElement;
  private origem: Ponto | null = null;
  private destino: Ponto | null = null;
  private campo: Campo | null = null;
  /** motivo de estar pedindo a origem — some assim que ela é definida */
  private aviso: string | null = null;

  constructor(ctx: Contexto) {
    this.ctx = ctx;
    this.el = document.createElement("div");
    this.el.id = "rota";
    this.el.innerHTML = `
      <div id="rotaLinhas">
        <button id="rotaOrigem" class="rota-campo" type="button">
          <span class="rota-marca rota-marca-a">A</span><span class="rota-texto"></span>
        </button>
        <button id="rotaDestino" class="rota-campo" type="button">
          <span class="rota-marca rota-marca-b">B</span><span class="rota-texto"></span>
        </button>
        <button id="rotaTrocar" class="rota-icone" type="button" aria-label="Inverter">⇅</button>
      </div>
      <div id="rotaResumo"></div>
      <div id="rotaLista" hidden></div>
      <div id="rotaBarra">
        <button id="rotaGps" type="button">Usar minha posição</button>
        <button id="rotaFechar" type="button">Fechar</button>
      </div>`;
    document.body.appendChild(this.el);

    this.$("rotaOrigem").addEventListener("click", () => this.escolher("origem"));
    this.$("rotaDestino").addEventListener("click", () => this.escolher("destino"));
    this.$("rotaTrocar").addEventListener("click", () => this.trocar());
    if (simulando()) this.$("rotaGps").textContent = "Usar posição simulada";
    this.$("rotaGps").addEventListener("click", () => void this.usarGps());
    this.$("rotaFechar").addEventListener("click", () => this.fechar());
  }

  private $(id: string): HTMLElement {
    return this.el.querySelector(`#${id}`) as HTMLElement;
  }

  get aberto(): boolean {
    return this.el.classList.contains("open");
  }

  get escolhendo(): Campo | null {
    return this.campo;
  }

  /**
   * Abre o percurso já com o destino escolhido — é o caminho comum: a pessoa
   * procurou uma editora e quer saber como chegar. A origem vem da última
   * usada; se não houver, da porta mais próxima do destino. Nos dois casos
   * fica escrita na tela e trocável, para nunca rotear de um lugar que o
   * visitante não escolheu sem ele perceber.
   */
  abrir(destino: Ponto): void {
    this.destino = destino;
    this.campo = null;
    this.ctx.aoEscolher(null);
    this.ctx.desenhaIncerteza(null, 0);
    this.esconderLista();
    if (!this.origem) this.origem = this.lembrada() ?? this.portaPara(destino);
    this.el.classList.add("open");
    this.atualiza();
  }

  fechar(): void {
    this.el.classList.remove("open");
    this.campo = null;
    this.destino = null;
    this.ctx.aoEscolher(null);
    this.ctx.desenhaRota(null);
    this.ctx.desenhaPontos(null, null);
    this.ctx.desenhaIncerteza(null, 0);
    this.esconderLista();
  }

  escolher(campo: Campo, aviso: string | null = null): void {
    this.aviso = aviso;
    this.campo = this.campo === campo ? null : campo;
    this.ctx.aoEscolher(this.campo);
    this.esconderLista();
    this.atualiza();
  }

  /** preenche o campo em escolha (ou o indicado) e recalcula */
  define(ponto: Ponto, campo: Campo | null = null): void {
    const alvo = campo ?? this.campo ?? "destino";
    if (alvo === "origem") {
      this.origem = ponto;
      this.lembra(ponto);
    } else {
      this.destino = ponto;
    }
    this.campo = null;
    this.aviso = null;
    this.ctx.aoEscolher(null);
    this.esconderLista();
    if (!this.aberto) this.el.classList.add("open");
    this.atualiza();
  }

  private trocar(): void {
    const a = this.origem;
    this.origem = this.destino;
    this.destino = a;
    if (this.origem) this.lembra(this.origem);
    this.esconderLista();
    this.atualiza();
  }

  private atualiza(): void {
    const texto = (id: string, p: Ponto | null, vazio: string) => {
      const b = this.$(id);
      (b.querySelector(".rota-texto") as HTMLElement).textContent = p ? p.rotulo : vazio;
      b.classList.toggle("vazio", !p);
      b.classList.toggle("ativo", this.campo === (id === "rotaOrigem" ? "origem" : "destino"));
    };
    texto("rotaOrigem", this.origem, "Onde você está?");
    texto("rotaDestino", this.destino, "Para onde vai?");
    this.ctx.desenhaPontos(this.origem, this.destino);

    const resumo = this.$("rotaResumo");
    if (this.campo) {
      const dica =
        this.campo === "origem"
          ? "busque ou toque no mapa onde você está"
          : "busque ou toque no mapa aonde quer ir";
      resumo.textContent = this.aviso
        ? `${this.aviso} — ${dica}`
        : dica[0].toUpperCase() + dica.slice(1);
      this.ctx.desenhaRota(null);
      return;
    }
    if (!this.origem || !this.destino) {
      resumo.textContent = "";
      this.ctx.desenhaRota(null);
      return;
    }
    const r = this.ctx.rotas.rota(this.origem.cel, this.destino.cel);
    if (!r) {
      resumo.textContent = "Sem caminho entre esses dois pontos";
      this.ctx.desenhaRota(null);
      return;
    }
    // ~1,25 m/s é passo de gente andando em feira cheia, olhando para os lados
    const min = Math.max(1, Math.round(r.metros / 75));
    resumo.textContent = `${Math.round(r.metros)} m · cerca de ${min} min a pé`;
    this.ctx.desenhaRota(r.cels);
    this.ctx.enquadra(r.cels);
  }

  // ---- GPS: opcional, degradável, nunca fonte de verdade ----

  private async usarGps(): Promise<void> {
    const resumo = this.$("rotaResumo");
    resumo.textContent = simulando() ? "Lendo posição simulada…" : "Procurando sinal…";
    const fix = await posicao(ESPERA_MS, BOM_M, ASSENTA_MS);

    if (typeof fix === "string") {
      // negado, indisponível e pendurado terminam igual: o visitante aponta.
      // Distinguir só serve para a mensagem não mentir sobre a causa.
      const motivo = {
        negado: "Sem permissão de localização",
        indisponivel: "Este navegador não dá acesso à localização",
        demorou: "Sem sinal de GPS aqui dentro",
      }[fix];
      this.escolher("origem", motivo);
      return;
    }

    const marca = fix.simulado ? " · simulado" : "";
    const { rotas } = this.ctx;
    // Um círculo maior que metade do menor lado do salão cobre boa parte das
    // fileiras: ordenar por ele não diria nada. O limite sai da própria malha
    // em vez de ser um número escolhido por mim.
    const limite = Math.min(...rotas.extensao()) / 2;
    if (fix.erro > limite) {
      this.escolher("origem", `Sinal fraco (± ${Math.round(fix.erro)} m${marca})`);
      return;
    }

    const cel = rotas.celula(fix.lng, fix.lat);
    // o alcance da busca por chão caminhável também sai do fix: com ±10 m não
    // faz sentido varrer 50 m, e com ±80 m varrer 50 m descartaria o certo
    if (!rotas.maisProximaLivre(fix.lng, fix.lat, Math.max(fix.erro, 15))) {
      this.escolher("origem", `Você parece estar fora do pavilhão${marca}`);
      return;
    }

    // Único caso em que o GPS decide sozinho: a porta é a coisa mais próxima
    // do fix. É onde o sensor é confiável (portão é área aberta, com céu à
    // vista) e onde a resposta é óbvia (quem acabou de entrar está na porta).
    // Bastar "porta a menos de 35 m" não serve: no meio do salão quase sempre
    // há uma saída nesse raio, e o app escolheria por conta própria um lugar
    // onde o visitante não está.
    const perto = this.ctx.candidatos(cel, fix.erro, MIN_OPCOES, MAX_OPCOES);
    const dPerto = perto.length ? rotas.distancia(perto[0].cel, cel) : Infinity;
    const porta = rotas
      .portas()
      .map((p) => ({ ...p, d: rotas.distancia(p.cel, cel) }))
      .sort((a, b) => a.d - b.d)[0];
    if (porta && porta.d <= Math.max(fix.erro, BOM_M) && porta.d <= dPerto) {
      this.ctx.desenhaIncerteza(null, 0);
      this.define({ rotulo: porta.nome, cel: porta.cel }, "origem");
      resumo.textContent =
        `${resumo.textContent} · origem pelo GPS${marca} (± ${Math.round(fix.erro)} m)`;
      return;
    }

    // longe de porta: o GPS não escolhe, só ordena. O círculo é honesto sobre
    // o tamanho da dúvida e a lista continua rolável até o fim do índice.
    this.ctx.desenhaIncerteza(cel, fix.erro);
    resumo.textContent =
      `Você está por aqui (± ${Math.round(fix.erro)} m${marca}). Qual destes está mais perto de você?`;
    const lista = this.$("rotaLista");
    lista.hidden = false;
    lista.innerHTML = perto
      .map(
        (p, i) =>
          `<button class="rota-op" data-i="${i}">${escapa(p.rotulo)}<span>${Math.round(
            rotas.distancia(p.cel, cel),
          )} m</span></button>`,
      )
      .join("");
    lista.onclick = (e) => {
      const b = (e.target as HTMLElement).closest<HTMLElement>(".rota-op");
      if (!b) return;
      this.ctx.desenhaIncerteza(null, 0);
      this.define(perto[Number(b.dataset.i)], "origem");
    };
  }

  private esconderLista(): void {
    const lista = this.$("rotaLista");
    lista.hidden = true;
    lista.innerHTML = "";
  }

  // ---- origem lembrada ----

  private lembra(p: Ponto): void {
    try {
      localStorage.setItem(LEMBRETE, JSON.stringify(p));
    } catch {
      /* modo privado: seguir sem lembrar é aceitável */
    }
  }

  /** só devolve se a célula ainda for livre — a malha muda a cada build */
  private lembrada(): Ponto | null {
    try {
      const cru = localStorage.getItem(LEMBRETE);
      if (!cru) return null;
      const p = JSON.parse(cru) as Ponto;
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

function escapa(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
}
