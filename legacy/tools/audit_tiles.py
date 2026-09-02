"""Gera pares de tiles (PDF original x nossos dados) para auditoria de fidelidade.

Cada região vira reference/audit/tile-R<i>-orig.png e tile-R<i>-dados.png na
mesma escala, para comparação lado a lado.
"""
import json
import os

import pymupdf

REGIONS = {
    "R1": (15, 100, 460, 420),
    "R2": (440, 100, 900, 420),
    "R3": (860, 100, 1310, 420),
    "R4": (15, 400, 460, 700),
    "R5": (440, 400, 900, 700),
    "R6": (860, 400, 1310, 700),
    "R7": (15, 680, 700, 965),
    "R8": (640, 680, 1310, 965),
    "R9": (1265, 590, 1600, 1010),
}
SCALE = 2.6

CAT_COLORS = {
    "expositor": (0.2, 0.5, 0.9),
    "patrocinador": (0.85, 0.65, 0.0),
    "entidade": (0.6, 0.2, 0.7),
    "alameda": (0.9, 0.3, 0.3),
    "travessa": (0.15, 0.5, 0.5),
    "cultural": (0.85, 0.1, 0.15),
    "alimentacao": (0.95, 0.55, 0.1),
    "servico": (0.4, 0.4, 0.4),
    "infra": (0.1, 0.6, 0.3),
    "externo": (0.75, 0.75, 0.76),
    "marcador": (0.5, 0.3, 0.6),
}

os.makedirs("reference/audit", exist_ok=True)
m = json.load(open("data/map.json"))
doc = pymupdf.open("reference/mapa-oficial.pdf")
page = doc[0]

# ---- documento com o render dos nossos dados (uma página, recortada por região) ----
W, H = m["page"]
render = pymupdf.open()
p2 = render.new_page(width=W, height=H)
shape = p2.new_shape()
for r in m["ruas"]:
    shape.draw_rect(pymupdf.Rect(*r["bbox"]))
    shape.finish(fill=(0.93, 0.9, 0.85), color=None)
for a in m["areas"]:
    shape.draw_polyline([pymupdf.Point(*p) for p in a["poly"] + a["poly"][:1]])
    c = CAT_COLORS[a["cat"]]
    shape.finish(fill=tuple(0.55 + 0.45 * v for v in c), color=c, width=0.5, closePath=True)
for s in m["stands"]:
    shape.draw_polyline([pymupdf.Point(*p) for p in s["poly"] + s["poly"][:1]])
    c = CAT_COLORS[s["cat"]]
    shape.finish(fill=tuple(0.65 + 0.35 * v for v in c), color=c, width=0.5, closePath=True)
shape.commit()
for s in m["stands"]:
    b = s["bbox"]
    if s["id"] and s["cat"] not in ("travessa",):
        p2.insert_text(pymupdf.Point(b[0] + 1, (b[1] + b[3]) / 2 + 2), s["id"], fontsize=4)
for a in m["areas"]:
    if a["code"]:
        b = a["bbox"]
        p2.insert_text(pymupdf.Point(b[0] + 2, (b[1] + b[3]) / 2 + 2), a["code"], fontsize=5)
for r in m["ruas"]:
    if r["name"]:
        b = r["bbox"]
        p2.insert_text(pymupdf.Point((b[0] + b[2]) / 2 - 14, (b[1] + b[3]) / 2 + 2),
                       r["name"], fontsize=5)

for name, (x0, y0, x1, y1) in REGIONS.items():
    clip = pymupdf.Rect(x0, y0, x1, y1)
    mat = pymupdf.Matrix(SCALE, SCALE)
    page.get_pixmap(clip=clip, matrix=mat).save(f"reference/audit/tile-{name}-orig.png")
    p2.get_pixmap(clip=clip, matrix=mat).save(f"reference/audit/tile-{name}-dados.png")
    print(name, "ok")
