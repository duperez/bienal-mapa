/** Ícones de POI no estilo "pin circular colorido com glifo branco" (a
 * linguagem do Google Maps), desenhados em canvas — zero assets externos. */
import type { Map as MlMap } from "maplibre-gl";

const SIZE = 42; // px @2x (rende ~21px na tela)

type Draw = (ctx: CanvasRenderingContext2D) => void;

function makeIcon(bg: string, draw: Draw): ImageData {
  const c = document.createElement("canvas");
  c.width = SIZE;
  c.height = SIZE;
  const ctx = c.getContext("2d")!;
  const r = SIZE / 2;

  // sombra leve + anel branco + disco colorido
  ctx.beginPath();
  ctx.arc(r, r + 1, r - 3, 0, Math.PI * 2);
  ctx.fillStyle = "rgba(0,0,0,0.25)";
  ctx.filter = "blur(1.5px)";
  ctx.fill();
  ctx.filter = "none";

  ctx.beginPath();
  ctx.arc(r, r, r - 2, 0, Math.PI * 2);
  ctx.fillStyle = "#ffffff";
  ctx.fill();

  ctx.beginPath();
  ctx.arc(r, r, r - 4, 0, Math.PI * 2);
  ctx.fillStyle = bg;
  ctx.fill();

  ctx.fillStyle = "#ffffff";
  ctx.strokeStyle = "#ffffff";
  ctx.save();
  draw(ctx);
  ctx.restore();
  return ctx.getImageData(0, 0, SIZE, SIZE);
}

/* glifos geométricos simples, centrados no canvas 42x42 */

const talheres: Draw = (ctx) => {
  ctx.lineWidth = 2.6;
  ctx.lineCap = "round";
  // garfo (esq): cabo + 3 dentes
  ctx.beginPath();
  ctx.moveTo(16, 12);
  ctx.lineTo(16, 30);
  ctx.stroke();
  for (const dx of [-3.4, 0, 3.4]) {
    ctx.beginPath();
    ctx.moveTo(16 + dx, 12);
    ctx.lineTo(16 + dx, 18);
    ctx.stroke();
  }
  // faca (dir): lâmina
  ctx.beginPath();
  ctx.moveTo(27, 12);
  ctx.quadraticCurveTo(30.5, 17, 27.5, 21.5);
  ctx.lineTo(27, 30);
  ctx.stroke();
};

const wc: Draw = (ctx) => {
  // duas figuras: cabeça + corpo
  for (const [cx, saia] of [
    [15, false],
    [27, true],
  ] as [number, boolean][]) {
    ctx.beginPath();
    ctx.arc(cx, 13.5, 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    if (saia) {
      ctx.moveTo(cx, 17);
      ctx.lineTo(cx + 5, 27);
      ctx.lineTo(cx - 5, 27);
    } else {
      ctx.rect(cx - 2.6, 17.5, 5.2, 9.5);
    }
    ctx.closePath();
    ctx.fill();
  }
};

const info: Draw = (ctx) => {
  ctx.font = `bold ${SIZE * 0.55}px system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("i", SIZE / 2, SIZE / 2 + 1);
};

const estrela: Draw = (ctx) => {
  const cx = SIZE / 2;
  const cy = SIZE / 2 + 1;
  const R = 9.5;
  const rIn = 4.2;
  ctx.beginPath();
  for (let i = 0; i < 10; i++) {
    const ang = -Math.PI / 2 + (i * Math.PI) / 5;
    const rr = i % 2 === 0 ? R : rIn;
    const x = cx + rr * Math.cos(ang);
    const y = cy + rr * Math.sin(ang);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.closePath();
  ctx.fill();
};

const entrada: Draw = (ctx) => {
  ctx.lineWidth = 2.6;
  ctx.lineCap = "round";
  // porta
  ctx.strokeRect(23, 12, 7, 18);
  // seta entrando
  ctx.beginPath();
  ctx.moveTo(10, 21);
  ctx.lineTo(20, 21);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(16.5, 16.5);
  ctx.lineTo(21.5, 21);
  ctx.lineTo(16.5, 25.5);
  ctx.stroke();
};

export function addPoiIcons(map: MlMap): void {
  const icones: Record<string, [string, Draw]> = {
    "poi-alimentacao": ["#e8871e", talheres],
    "poi-wc": ["#7c64ac", wc],
    "poi-servico": ["#7c64ac", info],
    "poi-cultural": ["#1a8bbf", estrela],
    "poi-entrada": ["#1e874b", entrada],
  };
  for (const [nome, [cor, draw]] of Object.entries(icones)) {
    map.addImage(nome, makeIcon(cor, draw), { pixelRatio: 2 });
  }
}
