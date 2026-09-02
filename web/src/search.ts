/** Índice e UI de busca — construído do próprio GeoJSON do mapa. */

export interface Hit {
  name: string;
  code: string | null;
  kind: "estande" | "area";
  cat: string;
  /** centro [lng, lat] para voar até o resultado */
  center: [number, number];
  feature: GeoJSON.Feature;
}

function normalize(s: string): string {
  return s
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase();
}

function centerOf(f: GeoJSON.Feature): [number, number] {
  const ring = (f.geometry as GeoJSON.Polygon).coordinates[0];
  let x = 0;
  let y = 0;
  for (const p of ring.slice(0, -1)) {
    x += p[0];
    y += p[1];
  }
  const n = ring.length - 1;
  return [x / n, y / n];
}

export function buildIndex(geojson: GeoJSON.FeatureCollection): Hit[] {
  const hits: Hit[] = [];
  for (const f of geojson.features) {
    const p = f.properties ?? {};
    if (p.kind !== "estande" && p.kind !== "area") continue;
    if (!p.name && !p.code) continue;
    hits.push({
      name: p.name ?? p.code,
      code: p.code ?? null,
      kind: p.kind,
      cat: p.cat,
      center: centerOf(f),
      feature: f,
    });
  }
  return hits;
}

export function search(index: Hit[], query: string, limit = 30): Hit[] {
  const q = normalize(query.trim());
  if (!q) return [];
  const starts: Hit[] = [];
  const contains: Hit[] = [];
  for (const h of index) {
    const name = normalize(h.name);
    const code = h.code ? normalize(h.code) : "";
    if (name.startsWith(q) || code.startsWith(q)) starts.push(h);
    else if (name.includes(q)) contains.push(h);
    if (starts.length >= limit) break;
  }
  return [...starts, ...contains].slice(0, limit);
}

export function attachSearchUI(index: Hit[], onPick: (h: Hit) => void): void {
  const wrap = document.createElement("div");
  wrap.id = "searchWrap";
  wrap.innerHTML = `
    <div id="searchPill">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>
      </svg>
      <input id="searchInput" type="search" placeholder="Buscar editora ou estande"
             autocomplete="off" enterkeyhint="search" />
      <button id="searchClear" aria-label="Limpar">✕</button>
    </div>
    <div id="searchResults" hidden></div>`;
  document.body.appendChild(wrap);

  const input = document.getElementById("searchInput") as HTMLInputElement;
  const clear = document.getElementById("searchClear") as HTMLButtonElement;
  const box = document.getElementById("searchResults") as HTMLDivElement;
  let current: Hit[] = [];

  function render(hits: Hit[], query: string): void {
    current = hits;
    if (!query) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    box.hidden = false;
    box.innerHTML = hits.length
      ? hits
          .map(
            (h, i) => `
        <button class="result" data-i="${i}">
          <span class="result-name">${escapeHtml(h.name)}</span>
          <span class="result-sub">${escapeHtml(subtitle(h))}</span>
        </button>`,
          )
          .join("")
      : `<div class="result-empty">Nenhum resultado — confere a grafia ou tenta parte do nome</div>`;
  }

  input.addEventListener("input", () => {
    const q = input.value;
    clear.style.display = q ? "flex" : "none";
    render(search(index, q), q.trim());
  });
  clear.addEventListener("click", () => {
    input.value = "";
    clear.style.display = "none";
    render([], "");
    input.blur();
  });
  box.addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement).closest<HTMLButtonElement>(".result");
    if (!btn) return;
    const hit = current[Number(btn.dataset.i)];
    box.hidden = true;
    input.blur();
    if (hit) onPick(hit);
  });
}

export function subtitle(h: Hit): string {
  if (h.kind === "area") {
    const catLabel: Record<string, string> = {
      alimentacao: "Alimentação",
      cultural: "Espaço cultural",
      servico: "Serviços",
      infra: "Serviços",
    };
    return catLabel[h.cat] ?? "Área";
  }
  if (!h.code) return "Estande";
  if (h.code.startsWith("TL")) return `Lugar nº ${Number(h.code.slice(2))} · Travessa Literária`;
  if (h.code.startsWith("TI")) return `Estande ${h.code} · Alameda dos Artistas`;
  const rua = /^(AA|BB|CC|DD|[A-K])(?=[0-9])/.exec(h.code)?.[1];
  return `Estande ${h.code}${rua ? ` · Rua ${rua}` : ""}`;
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
}
