"""Teste de aceite numérico: mapa.geojson vs PDF oficial.

Rasteriza o GeoJSON que o app consome, alinha com o render do PDF e mede IoU
por categoria. É o critério que faltava: sem isso, "ficou estranho" é opinião e
cada correção empurra o erro pra outro canto.
"""
import json
import math
import sys

import numpy as np
import pymupdf
from PIL import Image, ImageDraw

GEOJSON = "web/public/data/mapa.geojson"
VENUE = "data/venue.geojson"
PDF = "reference/mapa-oficial.pdf"
OUT = "reference/verificacao.png"

MAP_CLIP = (62.0, 140.0, 1545.0, 955.0)
HALL_M = 322.0
PX_PER_M = 5.7

CORES = {
    "expositor": (187, 230, 251),
    "cultural": (237, 33, 36),
    "patrocinador": (250, 238, 19),
    "entidade": (179, 127, 184),
    "infra": (192, 226, 202),
    "alimentacao": (250, 163, 26),
}
LEGENDA = (1068.0, 266.0, 1555.0, 485.0)   # legenda do PDF: não é planta
BASELINE = "data/iou-baseline.json"
TOLERANCIA = 0.01   # falha só em REGRESSÃO, não contra número mágico


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


def main():
    box = pymupdf.Rect(*MAP_CLIP)
    W = int(box.width * HALL_M / box.width * PX_PER_M)
    W = int(HALL_M * PX_PER_M)
    H = int(box.height * (HALL_M / box.width) * PX_PER_M)

    to_m = inverso()
    img = Image.new("RGB", (W, H), (250, 237, 210))
    dr = ImageDraw.Draw(img)

    feats = json.load(open(GEOJSON))["features"]
    ordem = {"piso": 0, "area": 1, "estande": 2}
    for f in sorted(feats, key=lambda f: (ordem.get(f["properties"]["kind"], 3),
                                          -f["properties"].get("area_m2", 0))):
        cat = f["properties"].get("cat")
        cor = CORES.get(cat, (198, 199, 200))
        for ring in f["geometry"]["coordinates"][:1]:
            pts = [tuple(v * PX_PER_M for v in to_m(*p)) for p in ring]
            if len(pts) >= 3:
                dr.polygon(pts, fill=cor)
    img.save(OUT)

    page = pymupdf.open(PDF)[0]
    pm = page.get_pixmap(clip=box, dpi=200)
    orig = Image.frombytes("RGB", (pm.width, pm.height), pm.samples).resize(
        (W, H), Image.LANCZOS)

    a = np.asarray(img).astype(int)
    b = np.asarray(orig).astype(int)

    # a caixa de legenda existe no PDF e não no modelo: comparar ali é ruído
    m_per_pt = HALL_M / box.width
    lx0 = int((LEGENDA[0] - box.x0) * m_per_pt * PX_PER_M)
    ly0 = int((LEGENDA[1] - box.y0) * m_per_pt * PX_PER_M)
    lx1 = int((LEGENDA[2] - box.x0) * m_per_pt * PX_PER_M)
    ly1 = int((LEGENDA[3] - box.y0) * m_per_pt * PX_PER_M)
    fora = np.ones(a.shape[:2], dtype=bool)
    fora[ly0:ly1, lx0:lx1] = False

    def mask(x, c, e=18):
        return ((np.abs(x[:, :, 0] - c[0]) < e) & (np.abs(x[:, :, 1] - c[1]) < e)
                & (np.abs(x[:, :, 2] - c[2]) < e))

    try:
        base = json.load(open(BASELINE))
    except OSError:
        base = {}

    ok = True
    atual = {}
    tot = inter = 0
    for cat, c in CORES.items():
        m1, m2 = mask(a, c) & fora, mask(b, c) & fora
        u = (m1 | m2).sum()
        if not u:
            continue
        i = (m1 & m2).sum()
        tot += i and i or 0
        tot = tot
        inter += i
        iou = float(i) / float(u)
        atual[cat] = round(iou, 4)
        ref = base.get(cat)
        if ref is None:
            flag = "  (novo)"
        elif iou < ref - TOLERANCIA:
            flag = f"  REGREDIU (era {ref:.4f})"
            ok = False
        else:
            flag = "  OK" if iou <= ref + TOLERANCIA else f"  MELHOROU (era {ref:.4f})"
        print(f"  IoU {cat:13s}: {iou:.4f}{flag}")

    if "--aceitar" in sys.argv:
        json.dump(atual, open(BASELINE, "w"), indent=1)
        print(f"baseline gravado em {BASELINE}")
    print(f"-> {OUT}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
