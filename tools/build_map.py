"""PDF oficial -> mapa.geojson do app. Transcrição, não síntese.

Cadeia: geometria literal do PDF -> classificação por cor -> código por
contenção do rótulo -> afim única para lng/lat.

O que muda em relação ao gerador antigo: a posição NUNCA vem de constante de
design. Ela vem do arquivo. Categoria, código e nome são metadados pendurados
em cima; se a classificação errar, o desenho continua no lugar certo.
"""
import json
import math
import re
import sys

import pymupdf

PDF = "reference/mapa-oficial.pdf"
VENUE = "data/venue.geojson"
STRUCT = "data/structure.json"
OUT = "web/public/data/mapa.geojson"

MAP_CLIP = (62.0, 140.0, 1545.0, 955.0)
LEGENDA = (1068.0, 266.0, 1555.0, 485.0)   # caixa da legenda: não é planta
HALL_M = 322.0

# cores da LEGENDA do próprio PDF -> categoria. Nada inventado.
PALETA = {
    (187, 230, 251): ("estande", "expositor"),
    (237, 33, 36): ("estande", "cultural"),
    (250, 238, 19): ("estande", "patrocinador"),
    (179, 127, 184): ("estande", "entidade"),
    (192, 226, 202): ("area", "infra"),
    (250, 163, 26): ("area", "alimentacao"),
}
# tons de vermelho/cinza que o PDF usa fora da legenda
# faces "3D" (extrusão) usam tons mais escuros da mesma cor: são sombra de
# desenho, não área ocupável. Só o topo do bloco vira feature.
ALIAS = {(235, 32, 40): (237, 33, 36), (238, 163, 26): (250, 163, 26)}
CINZA = ((198, 199, 200), (128, 129, 129), (35, 31, 32))  # estrutura/halls
CODE_RE = re.compile(r"[A-Z]{1,3}\d{1,3}[A-Z]?")


def rgb(c):
    return tuple(int(round(v * 255)) for v in c)


def snap(c, tol=18):
    c = ALIAS.get(c, c)
    for k in PALETA:
        if all(abs(a - b) <= tol for a, b in zip(c, k)):
            return k
    return None


def ring_area(r):
    s = 0.0
    for i in range(len(r)):
        x0, y0 = r[i]
        x1, y1 = r[(i + 1) % len(r)]
        s += x0 * y1 - x1 * y0
    return s / 2


def in_ring(pt, ring):
    x, y = pt
    inside = False
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i - 1) % n]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside


def title_pt(s):
    if not s:
        return None
    minus = {"de", "da", "do", "das", "dos", "e", "em", "a", "o"}
    out = []
    for i, w in enumerate(s.lower().split()):
        out.append(w if i and w in minus else w.capitalize())
    return " ".join(out)


# ---------------------------------------------------------------- geometria
def extrair(page, box):
    """Cada path preenchido do PDF -> anéis em METROS. Sem heurística."""
    m_per_pt = HALL_M / box.width

    def to_m(x, y):
        return (round((x - box.x0) * m_per_pt, 3), round((y - box.y0) * m_per_pt, 3))

    formas = []
    clip_lv = []
    for d in page.get_drawings(extended=True):
        lv = d.get("level", 0)
        while clip_lv and clip_lv[-1][0] >= lv:
            clip_lv.pop()
        if d["type"] == "clip":
            clip_lv.append((lv, d["scissor"]))
            continue
        if d["type"] == "group" or d.get("fill") is None:
            continue
        if not d["rect"].intersects(box):
            continue
        if clip_lv and not clip_lv[-1][1].intersects(d["rect"]):
            continue

        aneis, cur = [], []
        for it in d["items"]:
            if it[0] == "re":
                r = it[1]
                pts = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
                if len(it) > 2 and it[2] < 0:
                    pts.reverse()
                if cur:
                    aneis.append(cur)
                    cur = []
                aneis.append([to_m(*p) for p in pts])
            elif it[0] == "qu":
                q = it[1]
                if cur:
                    aneis.append(cur)
                    cur = []
                aneis.append([to_m(p.x, p.y) for p in (q.ul, q.ur, q.lr, q.ll)])
            elif it[0] == "l":
                a, b = to_m(it[1].x, it[1].y), to_m(it[2].x, it[2].y)
                if not cur:
                    cur = [a]
                elif cur[-1] != a:
                    aneis.append(cur)
                    cur = [a]
                cur.append(b)
            elif it[0] == "c":
                p0, c1, c2, p3 = it[1:5]
                a = to_m(p0.x, p0.y)
                if not cur:
                    cur = [a]
                elif cur[-1] != a:
                    aneis.append(cur)
                    cur = [a]
                for i in range(1, 7):
                    t, u = i / 6, 1 - i / 6
                    cur.append(to_m(
                        u**3 * p0.x + 3*u*u*t * c1.x + 3*u*t*t * c2.x + t**3 * p3.x,
                        u**3 * p0.y + 3*u*u*t * c1.y + 3*u*t*t * c2.y + t**3 * p3.y))
        if cur:
            aneis.append(cur)
        aneis = [a for a in aneis if len(a) >= 3 and abs(ring_area(a)) > 0.4]
        if not aneis:
            continue
        formas.append({"cor": rgb(d["fill"]), "aneis": aneis,
                       "seq": d.get("seqno", 0)})
    return formas, m_per_pt


def rotulos(page, box, m_per_pt):
    out = []
    for blk in page.get_text("dict", clip=box)["blocks"]:
        for line in blk.get("lines", []):
            for sp in line["spans"]:
                t = sp["text"].strip()
                if not t:
                    continue
                bb = sp["bbox"]
                out.append({
                    "txt": t,
                    "x": round(((bb[0] + bb[2]) / 2 - box.x0) * m_per_pt, 3),
                    "y": round(((bb[1] + bb[3]) / 2 - box.y0) * m_per_pt, 3),
                    "size": sp["size"] * m_per_pt,
                })
    return out


# ------------------------------------------------------------ georreferência
def georef():
    """Afim única metros->lng/lat, ancorada no polígono real do prédio (OSM)."""
    ring = json.load(open(VENUE))["features"][0]["geometry"]["coordinates"][0]
    lat0 = ring[0][1]
    mlat, mlon = 111320.0, 111320.0 * math.cos(math.radians(lat0))
    dx = (ring[1][0] - ring[0][0]) * mlon
    dy = (ring[1][1] - ring[0][1]) * mlat
    n = math.hypot(dx, dy)
    ux, uy = (dx / n, dy / n), (dy / n, -dx / n)  # leste, sul do prédio

    def frame(p):
        mx = (p[0] - ring[0][0]) * mlon
        my = (p[1] - ring[0][1]) * mlat
        return (mx * ux[0] + my * ux[1], mx * uy[0] + my * uy[1])

    west = min(x for x, y in map(frame, ring) if abs(y) < 5)
    nw = [ring[0][0] + west * ux[0] / mlon, ring[0][1] + west * ux[1] / mlat]

    def to_lnglat(x, y):
        mx = x * ux[0] + y * uy[0]
        my = x * ux[1] + y * uy[1]
        return [round(nw[0] + mx / mlon, 7), round(nw[1] + my / mlat, 7)]

    return to_lnglat


def subdividir(ext, codes):
    """Bloco com N códigos -> N células, cortadas nos pontos médios REAIS
    entre rótulos vizinhos.

    O PDF oficial frequentemente não desenha a divisa entre estandes vizinhos —
    só imprime os códigos dentro do mesmo retângulo. A divisão é derivada da
    posição dos rótulos, não de um passo de grid: o erro fica CONTIDO dentro do
    bloco real em vez de propagar pela fileira inteira.
    """
    xs = [p[0] for p in ext]
    ys = [p[1] for p in ext]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if len(codes) == 1:
        return [(ext, codes[0])]

    # linhas de rótulo: agrupa por y quando o bloco tem 2 fileiras costa a costa
    codes = sorted(codes, key=lambda c: (c["y"], c["x"]))
    tol = (y1 - y0) / 3
    linhas = []
    for c in codes:
        if linhas and abs(c["y"] - linhas[-1][0]) <= tol:
            linhas[-1][1].append(c)
        else:
            linhas.append((c["y"], [c]))
    linhas = [(y, sorted(g, key=lambda c: c["x"])) for y, g in linhas]

    cortes_y = [y0] + [(linhas[i][0] + linhas[i + 1][0]) / 2
                       for i in range(len(linhas) - 1)] + [y1]
    saida = []
    for i, (_, grupo) in enumerate(linhas):
        ya, yb = cortes_y[i], cortes_y[i + 1]
        cortes_x = [x0] + [(grupo[j]["x"] + grupo[j + 1]["x"]) / 2
                           for j in range(len(grupo) - 1)] + [x1]
        for j, c in enumerate(grupo):
            xa, xb = cortes_x[j], cortes_x[j + 1]
            saida.append(([(xa, ya), (xb, ya), (xb, yb), (xa, yb)], c))
    return saida


def main():
    page = pymupdf.open(PDF)[0]
    box = pymupdf.Rect(*MAP_CLIP)
    formas, m_per_pt = extrair(page, box)
    labels = rotulos(page, box, m_per_pt)
    codigos = [l for l in labels if CODE_RE.fullmatch(l["txt"])]
    nomes = [l for l in labels if not CODE_RE.fullmatch(l["txt"]) and l["size"] > 1.0]

    # a caixa da LEGENDA é desenho de legenda, não planta: fora.
    lx0, ly0 = ((LEGENDA[0] - box.x0) * m_per_pt, (LEGENDA[1] - box.y0) * m_per_pt)
    lx1, ly1 = ((LEGENDA[2] - box.x0) * m_per_pt, (LEGENDA[3] - box.y0) * m_per_pt)

    def na_legenda(r):
        return all(lx0 <= x <= lx1 and ly0 <= y <= ly1 for x, y in r)

    directory = json.load(open(STRUCT)).get("directory", {})
    to_lnglat = georef()

    def poly(ring, props):
        return {"type": "Feature", "properties": props,
                "geometry": {"type": "Polygon", "coordinates": [
                    [to_lnglat(x, y) for x, y in ring] + [to_lnglat(*ring[0])]]}}

    feats = []
    usados = set()
    for f in formas:
        alvo = snap(f["cor"])
        if alvo is None:
            if f["cor"] in CINZA:
                kind, cat = "piso", None  # nome de camada que o app já desenha
            else:
                continue
        else:
            kind, cat = PALETA[alvo]

        ext = max(f["aneis"], key=lambda r: abs(ring_area(r)))
        area = abs(ring_area(ext))
        if area < 1.0 or na_legenda(ext):
            continue

        # o código é o rótulo QUE ESTÁ DENTRO da forma. Sem inferir sequência,
        # sem sortear por proximidade de fileira.
        dentro = [c for c in codigos
                  if id(c) not in usados and in_ring((c["x"], c["y"]), ext)]
        for c in dentro:
            usados.add(id(c))

        if kind == "estande" and dentro:
            for ring, c in subdividir(ext, dentro):
                a = abs(ring_area(ring))
                props = {"kind": "estande", "cat": cat, "code": c["txt"],
                         "name": title_pt(directory.get(c["txt"])),
                         "area_m2": round(a, 1)}
                if a < 6:
                    props["mini"] = True
                feats.append(poly(ring, props))
            continue

        texto = [t for t in nomes if in_ring((t["x"], t["y"]), ext)]
        texto.sort(key=lambda t: (t["y"], t["x"]))
        nome = title_pt(" ".join(t["txt"] for t in texto)) if texto else None
        rings = [ext] + [r for r in f["aneis"]
                         if r is not ext and area > abs(ring_area(r)) > 1.0]
        coords = [[to_lnglat(x, y) for x, y in r] + [to_lnglat(*r[0])] for r in rings]
        feats.append({"type": "Feature", "geometry": {
            "type": "Polygon", "coordinates": coords},
            "properties": {"kind": kind, "cat": cat,
                           "code": dentro[0]["txt"] if dentro else None,
                           "name": nome, "area_m2": round(area, 1)}})

    json.dump({"type": "FeatureCollection", "features": feats},
              open(OUT, "w"), ensure_ascii=False)

    por = {}
    for f in feats:
        k = f["properties"]["cat"] or f["properties"]["kind"]
        por[k] = por.get(k, 0) + 1
    com_code = sum(1 for f in feats if f["properties"]["code"])
    com_nome = sum(1 for f in feats if f["properties"]["name"])
    print(f"features: {len(feats)}  com código: {com_code}  com nome: {com_nome}")
    print("  " + "  ".join(f"{k}={v}" for k, v in sorted(por.items())))


if __name__ == "__main__":
    sys.exit(main())
