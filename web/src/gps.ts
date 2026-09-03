/**
 * Leitura de posição, com simulação para teste.
 *
 * Existe um módulo só para isto porque o GPS é a parte do app que não dá para
 * exercitar sentado: o comportamento que interessa (fix pendurado, erro de
 * 40 m, permissão negada) só aparece dentro do pavilhão, no dia. Sem poder
 * simular, o código do GPS seria escrito no escuro e testado uma vez só.
 *
 * A simulação é explícita e visível: só liga por `?gps=sim` na URL e, quando
 * está ligada, o app escreve na tela que a posição é simulada. Nunca pode
 * acontecer de um fix falso passar por verdadeiro.
 */

export interface Fix {
  lng: number;
  lat: number;
  /** raio de confiança em metros, como o navegador reporta */
  erro: number;
  simulado: boolean;
}

const CHAVE = "bienal.gpsSim";

let simulado: Fix | null = null;
let ligado = false;

export function iniciaSimulacao(): boolean {
  const q = new URLSearchParams(location.search);
  ligado = q.get("gps") === "sim";
  if (!ligado) return false;
  const erro = Number(q.get("erro") ?? 30);
  const alvo = q.get("em");
  if (alvo) {
    const [lng, lat] = alvo.split(",").map(Number);
    if (isFinite(lng) && isFinite(lat)) simula(lng, lat, erro);
  } else {
    try {
      const cru = localStorage.getItem(CHAVE);
      if (cru) simulado = JSON.parse(cru) as Fix;
    } catch {
      /* sem simulação guardada */
    }
  }
  return true;
}

export function simulando(): boolean {
  return ligado;
}

export function fixSimulado(): Fix | null {
  return simulado;
}

export function simula(lng: number, lat: number, erro: number): Fix {
  simulado = { lng, lat, erro, simulado: true };
  try {
    localStorage.setItem(CHAVE, JSON.stringify(simulado));
  } catch {
    /* modo privado */
  }
  return simulado;
}

export type Falha = "negado" | "indisponivel" | "demorou";

/**
 * O melhor fix que aparecer dentro da janela de espera, ou o motivo de não ter.
 *
 * `watchPosition` em vez de `getCurrentPosition` porque o primeiro fix indoor
 * costuma vir de antena de celular, com centenas de metros de `accuracy`, e
 * só alguns segundos depois o wifi refina para dezenas. Ficar com o primeiro
 * jogaria fora justamente a leitura útil. Como `accuracy` é o raio de 95% de
 * confiança, "melhor" aqui tem significado preciso: o menor círculo.
 *
 * Sai antes da hora em dois casos, porque tela parada é o pior desfecho: se
 * o fix já for bom o bastante para o corredor, ou se um fix qualquer chegou e
 * `assenta` ms se passaram sem nada melhor. Sem a segunda regra o app espera
 * a janela inteira em toda leitura indoor, já que lá dentro a precisão quase
 * nunca chega ao patamar bom.
 *
 * O relógio próprio não é redundância com o `timeout` da API: há navegador
 * que segura o callback além do prazo pedido, e dentro de pavilhão o desfecho
 * mais comum é justamente esse — nem sucesso nem erro, só silêncio.
 */
export function posicao(espera: number, bom: number, assenta: number): Promise<Fix | Falha> {
  if (simulado) return Promise.resolve(simulado);
  if (!navigator.geolocation) return Promise.resolve("indisponivel");
  return new Promise<Fix | Falha>((ok) => {
    let melhor: Fix | null = null;
    let vivo = true;
    let paciencia: ReturnType<typeof setTimeout> | undefined;
    const encerra = (r: Fix | Falha) => {
      if (!vivo) return;
      vivo = false;
      clearTimeout(relogio);
      clearTimeout(paciencia);
      navigator.geolocation.clearWatch(id);
      ok(r);
    };
    const relogio = setTimeout(() => encerra(melhor ?? "demorou"), espera + 200);
    const id = navigator.geolocation.watchPosition(
      (p) => {
        const fix: Fix = {
          lng: p.coords.longitude,
          lat: p.coords.latitude,
          erro: p.coords.accuracy,
          simulado: false,
        };
        if (!melhor || fix.erro < melhor.erro) melhor = fix;
        if (melhor.erro <= bom) return encerra(melhor);
        clearTimeout(paciencia);
        paciencia = setTimeout(() => encerra(melhor!), assenta);
      },
      (e) => {
        // erro depois de um fix bom não apaga o fix
        if (melhor) return encerra(melhor);
        encerra(
          e.code === e.PERMISSION_DENIED
            ? "negado"
            : e.code === e.TIMEOUT
              ? "demorou"
              : "indisponivel",
        );
      },
      { enableHighAccuracy: true, timeout: espera, maximumAge: 60000 },
    );
  });
}
