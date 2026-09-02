"""Renderiza data/map.json para QA visual: overlay sobre o PDF e render puro."""
import json

import pymupdf

m = json.load(open("data/map.json"))

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

# ---- 1) overlay: contornos extraídos sobre o PDF original ----
doc = pymupdf.open("reference/mapa-oficial.pdf")
page = doc[0]
shape = page.new_shape()
for s in m["stands"]:
    shape.draw_polyline([pymupdf.Point(*p) for p in s["poly"] + s["poly"][:1]])
    shape.finish(color=(1, 0, 1), width=1.2)
for a in m["areas"]:
    shape.draw_polyline([pymupdf.Point(*p) for p in a["poly"] + a["poly"][:1]])
    shape.finish(color=(0, 0.8, 0.2), width=1.2)
for r in m["ruas"]:
    b = r["bbox"]
    shape.draw_rect(pymupdf.Rect(*b))
    shape.finish(color=(0, 0.4, 1), width=1.0)
shape.commit()
pix = page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6))
pix.save("reference/qa-overlay.png")

# ---- 2) render puro: só os dados extraídos ----
W, H = m["page"]
out = pymupdf.open()
p2 = out.new_page(width=W, height=H)
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
    if s["id"]:
        p2.insert_text(pymupdf.Point(b[0] + 1, (b[1] + b[3]) / 2 + 2), s["id"], fontsize=4)
for a in m["areas"]:
    if a["code"]:
        b = a["bbox"]
        p2.insert_text(pymupdf.Point(b[0] + 2, (b[1] + b[3]) / 2 + 2), a["code"], fontsize=5)
pix = p2.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6))
pix.save("reference/qa-puro.png")
print("ok: reference/qa-overlay.png reference/qa-puro.png")
