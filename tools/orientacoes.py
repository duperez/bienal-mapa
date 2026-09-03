"""Desenha o mapa da Bienal dentro do prédio real, nas quatro orientações.

Serve para uma coisa só: comparar com o render aéreo oficial e decidir de que
lado o desenho entra. A `afere_ancora` mede a distância das portas às marquises
e dá um vencedor, mas essa métrica não sabe distinguir um espelhamento de uma
rotação de 180 graus — e a diferença importa, porque nenhum organizador imprime
mapa espelhado. Olho humano com o render ao lado resolve em segundos o que o
número não resolve.

Gera reference/orientacoes.png. Não altera dado nenhum.
"""
import json
import sys

import pymupdf

sys.path.insert(0, "tools")
from afere_ancora import caixa, quadro  # noqa: E402

SAIDA = "reference/orientacoes.png"
ESC = 1.6  # pixels por metro
MARGEM = 24
LARGURAS = [14127, 15534, 12602, 12602, 12874]  # m2 dos Expo 1..5, planta oficial


def main():
    para_m, predio = quadro()
    px = [p[0] for p in predio]
    py = [p[1] for p in predio]
    lx, ly = max(px) - min(px), max(py) - min(py)

    feats = json.load(open("web/public/data/mapa.geojson"))["features"]
    blocos = [
        caixa(f["geometry"]["coordinates"][0], para_m)
        for f in feats
        if f["properties"]["kind"] in ("estande", "area")
    ]
    portas = [
        para_m(*f["geometry"]["coordinates"])
        for f in feats
        if f["properties"]["kind"] == "poi"
        and (
            f["properties"].get("cat") in ("entrada", "saida")
            or "acesso" in (f["properties"].get("name") or "").lower()
        )
    ]
    marq = [
        caixa(f["geometry"]["coordinates"][0], para_m)
        for f in json.load(open("data/controle-osm.geojson"))["features"]
    ]
    dx0 = min(b[0] for b in blocos)
    dx1 = max(b[2] for b in blocos)
    dy0 = min(b[1] for b in blocos)
    dy1 = max(b[3] for b in blocos)

    casos = [
        ("como está hoje", False, False),
        ("espelhado na horizontal", False, True),
        ("girado 180 graus", True, True),
        ("espelhado na vertical", True, False),
    ]
    cw = lx * ESC + 2 * MARGEM
    ch = ly * ESC + 2 * MARGEM + 26
    doc = pymupdf.open()
    pag = doc.new_page(width=cw * 2, height=ch * 2)

    for k, (titulo, esp, sul) in enumerate(casos):
        ox = (k % 2) * cw + MARGEM
        oy = (k // 2) * ch + MARGEM + 22
        pag.insert_text((ox, oy - 8), titulo, fontsize=11, color=(0, 0, 0))

        def P(x, y):
            return pymupdf.Point(ox + (x - min(px)) * ESC, oy + (y - min(py)) * ESC)

        def R(b):
            return pymupdf.Rect(P(b[0], b[1]), P(b[2], b[3])).normalize()

        pag.draw_polyline([P(*p) for p in predio], color=(0.1, 0.1, 0.1), width=1.4)
        for m in marq:  # marquises: onde estão as entradas de verdade
            pag.draw_rect(R(m), color=None, fill=(1, 0.75, 0.2), fill_opacity=0.85)

        x = 0
        for a in LARGURAS[:-1]:  # divisórias previstas entre os Expo
            x += a / ly
            pag.draw_line(P(x, 0), P(x, ly), color=(0.6, 0.6, 0.6), width=0.5, dashes="[3] 0")

        def vira(x, y):
            return (dx0 + dx1 - x if esp else x, dy0 + dy1 - y if sul else y)

        for a, b, c, d in blocos:
            x0, y0 = vira(a, b)
            x1, y1 = vira(c, d)
            pag.draw_rect(R((x0, y0, x1, y1)), color=None, fill=(0.45, 0.55, 0.75), fill_opacity=0.55)
        for p in portas:
            q = P(*vira(*p))
            pag.draw_circle(q, 4, color=None, fill=(0.85, 0.1, 0.1))

    pag.get_pixmap(dpi=150).save(SAIDA)
    print(f"{SAIDA} gravado — laranja = marquises reais, vermelho = portas do evento")


if __name__ == "__main__":
    main()
