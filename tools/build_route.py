"""Malha de rota: superfície caminhável -> grade navegável + pontos de acesso.

Por que grade, e não um grafo das vias: as vias derivadas são o *rótulo* dos
corredores, não a topologia deles. Elas não se nodam nos cruzamentos, não
chegam até a porta do estande e não cobrem praça nem avental. Rotear por elas
exigiria costurar tudo isso à mão — que é exatamente o que este projeto se
proíbe de fazer.

A grade não tem esse problema: ela é a própria superfície livre, amostrada. O
caminho sai de onde dá para andar, e as vias voltam depois só para escrever a
instrução ("siga pela RUA E").

Saída: web/public/data/malha.json — um bitmask das células livres (compacto o
bastante para caber offline) mais o ponto de acesso de cada estande. O A* roda
no navegador, porque a origem é o visitante e ela muda a cada passo.
"""
import base64
import json
import math
import sys
from collections import deque

import pymupdf
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep

sys.path.insert(0, "tools")
from build_map import MAP_CLIP, PDF, assentamento, extrair, georef  # noqa: E402
from verify_map import inverso  # noqa: E402

SAIDA = "web/public/data/malha.json"
GEOJSON = "web/public/data/mapa.geojson"

PASSO = 0.5      # m: metade da fresta mínima (LARG_MIN=2 m), 4 células de vão
ALCANCE = 4.0    # m: distância máxima entre um bloco e sua célula de acesso


def em_metros(geom, to_m):
    """Polygon/MultiPolygon do GeoJSON -> shapely em metros."""
    if geom["type"] == "Polygon":
        aneis = [geom["coordinates"]]
    elif geom["type"] == "MultiPolygon":
        aneis = geom["coordinates"]
    else:
        return None
    return unary_union([
        Polygon([to_m(*c) for c in a[0]], [[to_m(*c) for c in r] for r in a[1:]])
        for a in aneis])


def rasteriza(livre, x0, y0, w, h):
    """Célula é livre se o centro dela cai na superfície caminhável.

    Testar pelo centro (e não pela área) é o que mantém a grade conservadora:
    célula meio ocupada não vira passagem.
    """
    dentro = prep(livre)
    bits = bytearray(w * h)
    for j in range(h):
        y = y0 + (j + 0.5) * PASSO
        base = j * w
        for i in range(w):
            if dentro.contains(Point(x0 + (i + 0.5) * PASSO, y)):
                bits[base + i] = 1
    return bits


VIZ = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
       (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)]


def alcancavel(bits, w, h, sementes):
    """BFS 8-vizinhos a partir das sementes. Diagonal só se os dois ortogonais
    também estiverem livres — senão a rota corta quina de estande."""
    visto = bytearray(w * h)
    fila = deque()
    for c in sementes:
        if bits[c] and not visto[c]:
            visto[c] = 1
            fila.append(c)
    while fila:
        c = fila.popleft()
        cx, cy = c % w, c // w
        for dx, dy, _ in VIZ:
            nx, ny = cx + dx, cy + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            n = ny * w + nx
            if visto[n] or not bits[n]:
                continue
            if dx and dy and not (bits[cy * w + nx] and bits[ny * w + cx]):
                continue
            visto[n] = 1
            fila.append(n)
    return visto


def acesso(g, bits, w, h, x0, y0):
    """Célula livre mais próxima da borda do bloco, dentro de ALCANCE.

    É o equivalente da porta: o PDF não desenha portas, então o ponto de acesso
    é derivado, e fica marcado como tal em quem consome.
    """
    b = g.bounds
    r = int(ALCANCE / PASSO) + 1
    i0 = max(0, int((b[0] - x0) / PASSO) - r)
    i1 = min(w - 1, int((b[2] - x0) / PASSO) + r)
    j0 = max(0, int((b[1] - y0) / PASSO) - r)
    j1 = min(h - 1, int((b[3] - y0) / PASSO) + r)
    melhor, dmin = None, ALCANCE
    for j in range(j0, j1 + 1):
        for i in range(i0, i1 + 1):
            if not bits[j * w + i]:
                continue
            d = g.distance(Point(x0 + (i + 0.5) * PASSO, y0 + (j + 0.5) * PASSO))
            if d < dmin:
                melhor, dmin = (i, j), d
    return melhor


def main():
    page = pymupdf.open(PDF)[0]
    box = pymupdf.Rect(*MAP_CLIP)
    formas, mpp = extrair(page, box)
    para_predio, para_desenho = assentamento(formas, box, mpp)
    predio_to_m = inverso()

    def to_m(lng, lat):
        return para_desenho(*predio_to_m(lng, lat))

    base = georef()

    def to_lnglat(x, y):
        return base(*para_predio(x, y))

    feats = json.load(open(GEOJSON))["features"]
    circ = unary_union([em_metros(f["geometry"], to_m) for f in feats
                        if f["properties"]["kind"] == "circulacao"])
    blocos = [(f["properties"], em_metros(f["geometry"], to_m)) for f in feats
              if f["properties"]["kind"] in ("estande", "area")
              and f["geometry"]["type"] == "Polygon"]
    livre = circ.difference(unary_union([g for _, g in blocos]))

    bx0, by0, bx1, by1 = livre.bounds
    x0, y0 = math.floor(bx0), math.floor(by0)
    w = int(math.ceil((bx1 - x0) / PASSO)) + 1
    h = int(math.ceil((by1 - y0) / PASSO)) + 1
    bits = rasteriza(livre, x0, y0, w, h)
    print(f"grade: {w} x {h} células de {PASSO} m  "
          f"({sum(bits)} livres, {100 * sum(bits) / (w * h):.0f}% da caixa)")

    # portas do evento: os POIs de entrada e saída, encostados na grade
    portas = {}
    for f in feats:
        p = f["properties"]
        if p["kind"] != "poi" or not p.get("name"):
            continue
        x, y = to_m(*f["geometry"]["coordinates"])
        cel = acesso(Point(x, y).buffer(0.1), bits, w, h, x0, y0)
        if cel:
            portas.setdefault(p["name"], []).append(cel)

    sementes = [j * w + i for lst in portas.values() for i, j in lst]
    visto = alcancavel(bits, w, h, sementes)
    ilhadas = sum(bits) - sum(visto)
    print(f"portas: {sum(len(v) for v in portas.values())} em {len(portas)} nomes")
    print(f"células livres sem ligação com nenhuma porta: {ilhadas}")

    acessos, sem_acesso, sem_rota = {}, [], []
    for p, g in blocos:
        chave = p.get("code") or p.get("name")
        if not chave or chave in acessos:
            continue
        cel = acesso(g, bits, w, h, x0, y0)
        if cel is None:
            sem_acesso.append(chave)
            continue
        if not visto[cel[1] * w + cel[0]]:
            sem_rota.append(chave)
            continue
        acessos[chave] = list(cel)
    print(f"blocos com acesso roteável: {len(acessos)}")
    if sem_acesso:
        print(f"  sem célula livre a {ALCANCE} m: {len(sem_acesso)} -> "
              f"{', '.join(sem_acesso[:8])}")
    if sem_rota:
        print(f"  com acesso mas sem rota até porta: {len(sem_rota)} -> "
              f"{', '.join(sem_rota[:8])}")

    o = to_lnglat(x0 + PASSO / 2, y0 + PASSO / 2)
    ex = to_lnglat(x0 + PASSO / 2 + PASSO, y0 + PASSO / 2)
    ey = to_lnglat(x0 + PASSO / 2, y0 + PASSO / 2 + PASSO)
    json.dump({
        "passo": PASSO, "w": w, "h": h,
        # afim da grade -> lng/lat: origem é o centro da célula (0,0) e cada
        # passo em i/j soma ex/ey. Evita reimplementar a georreferência no app.
        "origem": o,
        "ex": [round(ex[0] - o[0], 9), round(ex[1] - o[1], 9)],
        "ey": [round(ey[0] - o[0], 9), round(ey[1] - o[1], 9)],
        "livre": base64.b64encode(
            bytes(int("".join(str(b) for b in bits[k:k + 8]).ljust(8, "0"), 2)
                  for k in range(0, len(bits), 8))).decode(),
        "acessos": acessos,
        "portas": {k: v for k, v in portas.items()},
    }, open(SAIDA, "w"), separators=(",", ":"))
    import os
    print(f"{SAIDA}: {os.path.getsize(SAIDA) / 1024:.1f} KB")
    return 0 if not sem_rota else 1


if __name__ == "__main__":
    sys.exit(main())
