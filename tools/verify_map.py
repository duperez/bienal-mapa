"""Teste de aceite VETORIAL: mapa.geojson vs PDF oficial.

Mede o que importa — geometria — em vez de pixels. Para cada forma preenchida
do PDF que o build deveria ter transcrito, procura a feature correspondente no
GeoJSON e compara área, IoU e deriva de centroide em centímetros.

Por que vetorial: o teste raster anterior punia antialiasing e formas de 2 px
(a categoria "entidade" dava IoU 0,09 sendo geometricamente perfeita) e era
enganado por logotipos desenhados por cima. Aqui, 1,0 é 1,0.

Uso:
    python tools/verify_map.py            # compara com o baseline
    python tools/verify_map.py --aceitar  # grava o baseline atual
"""
import json
import math
import sys

import pymupdf
from shapely.geometry import Polygon
from shapely.strtree import STRtree

sys.path.insert(0, "tools")
from build_map import (MAP_CLIP, LEGENDA, TRAVESSA, VENUE, classificar,
                       extrair, ring_area)  # noqa: E402

GEOJSON = "web/public/data/mapa.geojson"
BASELINE = "data/aceite-baseline.json"
TOL_IOU = 0.98        # forma considerada fiel
TOL_DERIVA_CM = 5.0   # deriva máxima de centroide aceitável


def inverso():
    """lng/lat -> metros no frame do prédio (inverso exato do build)."""
    ring = json.load(open(VENUE))["features"][0]["geometry"]["coordinates"][0]
    lat0 = ring[0][1]
    mlat, mlon = 111320.0, 111320.0 * math.cos(math.radians(lat0))
    dx = (ring[1][0] - ring[0][0]) * mlon
    dy = (ring[1][1] - ring[0][1]) * mlat
    n = math.hypot(dx, dy)
    ux, uy = (dx / n, dy / n), (dy / n, -dx / n)

    def frame(p):
        mx = (p[0] - ring[0][0]) * mlon
        my = (p[1] - ring[0][1]) * mlat
        return (mx * ux[0] + my * ux[1], mx * uy[0] + my * uy[1])

    west = min(x for x, y in map(frame, ring) if abs(y) < 5)
    nw = [ring[0][0] + west * ux[0] / mlon, ring[0][1] + west * ux[1] / mlat]

    def to_m(lng, lat):
        mx = (lng - nw[0]) * mlon
        my = (lat - nw[1]) * mlat
        return (mx * ux[0] + my * ux[1], mx * uy[0] + my * uy[1])

    return to_m


def limpa(p):
    return p if p.is_valid else p.buffer(0)


def main():
    box = pymupdf.Rect(*MAP_CLIP)
    page = pymupdf.open("reference/mapa-oficial.pdf")[0]
    formas, m_per_pt = extrair(page, box)

    lx0, ly0 = ((LEGENDA[0] - box.x0) * m_per_pt, (LEGENDA[1] - box.y0) * m_per_pt)
    lx1, ly1 = ((LEGENDA[2] - box.x0) * m_per_pt, (LEGENDA[3] - box.y0) * m_per_pt)

    tv0, tv1 = ((TRAVESSA[0] - box.x0) * m_per_pt, (TRAVESSA[1] - box.y0) * m_per_pt)
    tv2, tv3 = ((TRAVESSA[2] - box.x0) * m_per_pt, (TRAVESSA[3] - box.y0) * m_per_pt)

    # o que o PDF manda existir, pela MESMA regra que o build usa
    esperado = []
    for f in formas:
        ext = max(f["aneis"], key=lambda r: abs(ring_area(r)))
        area = abs(ring_area(ext))
        if area < 0.5 or all(lx0 <= x <= lx1 and ly0 <= y <= ly1 for x, y in ext):
            continue
        xs = [p[0] for p in ext]
        ys = [p[1] for p in ext]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        na_tv = tv0 <= cx <= tv2 and tv1 <= cy <= tv3
        kind, cat = classificar(f["cor"], ext, area, na_tv)
        if kind is None or kind == "poi":   # POI vira Point, não polígono
            continue
        buracos = [r for r in f["aneis"] if r is not ext and abs(ring_area(r)) > 1.0]
        esperado.append((cat or kind, limpa(Polygon(ext, buracos))))

    to_m = inverso()
    feats = json.load(open(GEOJSON))["features"]
    modelo = []
    for f in feats:
        if f["geometry"]["type"] != "Polygon":
            continue
        anel = [to_m(*p) for p in f["geometry"]["coordinates"][0]]
        buracos = [[to_m(*p) for p in r] for r in f["geometry"]["coordinates"][1:]]
        modelo.append((f["properties"], limpa(Polygon(anel, buracos))))

    geoms = [g for _, g in modelo]
    tree = STRtree(geoms)

    res = {}
    derivas = []
    orfaos = []
    for cat, alvo in esperado:
        cand = tree.query(alvo)
        melhor, iou = None, 0.0
        for i in cand:
            g = geoms[i]
            u = alvo.union(g).area
            if u <= 0:
                continue
            v = alvo.intersection(g).area / u
            if v > iou:
                iou, melhor = v, g
        # bloco subdividido em N células: a união das células é que deve casar
        if iou < TOL_IOU and cand.size:
            partes = [geoms[i] for i in cand if alvo.contains(geoms[i].centroid)]
            if partes:
                from shapely.ops import unary_union
                u = unary_union(partes)
                v = alvo.intersection(u).area / alvo.union(u).area
                if v > iou:
                    iou, melhor = v, u
        d = res.setdefault(cat, {"total": 0, "fiel": 0})
        d["total"] += 1
        if iou >= TOL_IOU:
            d["fiel"] += 1
            derivas.append(alvo.centroid.distance(melhor.centroid) * 100)
        else:
            orfaos.append((cat, round(iou, 3),
                           [round(v, 1) for v in alvo.centroid.coords[0]]))

    print(f"{'categoria':14s} {'fiéis':>12s}   cobertura")
    atual = {}
    for cat in sorted(res):
        d = res[cat]
        cob = d["fiel"] / d["total"]
        atual[cat] = round(cob, 4)
        print(f"  {cat:12s} {d['fiel']:5d}/{d['total']:<5d}   {cob:6.1%}")

    dmax = max(derivas) if derivas else 0.0
    atual["_deriva_cm"] = round(dmax, 2)
    print(f"\nderiva máxima de centroide: {dmax:.2f} cm "
          f"({'OK' if dmax <= TOL_DERIVA_CM else 'ALTA'})")
    if orfaos:
        print(f"formas do PDF sem par fiel: {len(orfaos)}")
        for o in sorted(orfaos, key=lambda o: o[1])[:8]:
            print(f"   {o[0]:12s} IoU {o[1]:.3f}  em {o[2]} m")

    if "--aceitar" in sys.argv:
        json.dump(atual, open(BASELINE, "w"), indent=1)
        print(f"baseline gravado em {BASELINE}")
        return 0

    try:
        base = json.load(open(BASELINE))
    except OSError:
        print("sem baseline — rode com --aceitar")
        return 0

    ok = True
    for cat, v in atual.items():
        ref = base.get(cat)
        if ref is None:
            continue
        if cat == "_deriva_cm":
            if v > ref + 1.0:
                print(f"REGREDIU deriva: {v} cm (era {ref})")
                ok = False
        elif v < ref - 0.01:
            print(f"REGREDIU {cat}: {v:.1%} (era {ref:.1%})")
            ok = False
    print("aceite: OK" if ok else "aceite: FALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
