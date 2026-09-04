"""Transcrição literal: mapa-oficial.pdf -> geometria própria (SVG) -> PNG.

A geometria NÃO é sintetizada. Cada path vetorial do PDF é lido, convertido por
UMA afim global (pt do PDF -> metros do prédio) e re-emitido em SVG próprio.
Nenhuma constante de design, nenhum empilhamento de fileira, nenhum snap de
grid. Se o pavilhão real está torto, sai torto — que é o certo.

Pontos que exigem fidelidade (e que quebram qualquer renderizador ingênuo):
- um path do PDF pode ter vários subpaths, e a regra de winding define os furos;
- clip paths escondem geometria que existe no arquivo mas não na página;
- opacidade de grupo.
"""
import json
import re
import sys

import cairosvg
import pymupdf

PDF = "reference/mapa-oficial.pdf"
OUT_SVG = "reference/transcrito.svg"
OUT_PNG = "reference/transcrito.png"
OUT_JSON = "data/transcrito.json"

MAP_CLIP = (62.0, 140.0, 1545.0, 955.0)
HALL_M = 322.0          # lado maior do hall (OSM way 203621978)
PX_PER_M = 5.7          # resolução do PNG de conferência

CODE_RE = re.compile(r"[A-Z]{1,3}\d{1,3}[A-Z]?")


def hexcol(c):
    return "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in c)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main():
    page = pymupdf.open(PDF)[0]
    box = pymupdf.Rect(*MAP_CLIP)

    # ---- afim global única: pt do PDF -> metros do prédio ----
    M_PER_PT = HALL_M / box.width
    X0, Y0 = box.x0, box.y0

    def to_m(x, y):
        return ((x - X0) * M_PER_PT, (y - Y0) * M_PER_PT)

    def p(x, y):
        mx, my = to_m(x, y)
        return f"{mx * PX_PER_M:.2f},{my * PX_PER_M:.2f}"

    W = box.width * M_PER_PT * PX_PER_M
    H = box.height * M_PER_PT * PX_PER_M

    def path_data(items):
        """Todos os subpaths de UM path do PDF, encadeados.

        Segmentos consecutivos que compartilham ponto continuam o mesmo
        subpath — quebrar cada 'l' num "M...L..." destrói o anel e, com winding
        nonzero, mata os furos (a Praça vira um bloco cinza sólido).
        """
        d = []
        cur = None
        for item in items:
            k = item[0]
            if k in ("re", "qu"):
                if k == "re":
                    r = item[1]
                    # o 3º campo é a orientação do subpath: é ela que decide se
                    # o retângulo preenche ou FURA (regra nonzero).
                    pts = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
                    if len(item) > 2 and item[2] < 0:
                        pts.reverse()
                else:
                    q = item[1]
                    pts = [(q.ul.x, q.ul.y), (q.ur.x, q.ur.y),
                           (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)]
                d.append("M" + " L".join(p(x, y) for x, y in pts) + " Z")
                cur = None
                continue
            if k == "l":
                a, b = (item[1].x, item[1].y), (item[2].x, item[2].y)
                seg, end = f"L{p(*b)}", b
            elif k == "c":
                p0, c1, c2, p3 = item[1:5]
                a = (p0.x, p0.y)
                seg = f"C{p(c1.x, c1.y)} {p(c2.x, c2.y)} {p(p3.x, p3.y)}"
                end = (p3.x, p3.y)
            else:
                continue
            if cur is None or abs(cur[0] - a[0]) > 1e-6 or abs(cur[1] - a[1]) > 1e-6:
                d.append(f"M{p(*a)}")
            d.append(seg)
            cur = end
        return " ".join(d)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" '
           f'height="{H:.0f}" viewBox="0 0 {W:.2f} {H:.2f}">']

    clip_stack = []
    open_groups = []
    defs = []
    shapes = []
    n_clip = 0

    def close_to(lvl):
        while open_groups and open_groups[-1] >= lvl:
            open_groups.pop()
            out.append("</g>")
        while clip_stack and clip_stack[-1] >= lvl:
            clip_stack.pop()

    for d in page.get_drawings(extended=True):
        lvl = d.get("level", 0)
        close_to(lvl)

        if d["type"] == "clip":
            cid = f"c{n_clip}"
            n_clip += 1
            path = path_data(d["items"])
            rule = "evenodd" if d.get("even_odd") else "nonzero"
            defs.append(f'<clipPath id="{cid}" clipPathUnits="userSpaceOnUse">'
                        f'<path clip-rule="{rule}" d="{path}"/></clipPath>')
            out.append(f'<g clip-path="url(#{cid})">')
            open_groups.append(lvl)
            clip_stack.append(lvl)
            continue

        if d["type"] == "group":
            out.append(f'<g opacity="{d.get("opacity", 1.0):.3f}">')
            open_groups.append(lvl)
            continue

        if not d["rect"].intersects(box):
            continue

        # UM path do PDF = UM <path> no SVG, com todos os subpaths juntos.
        # É isso que preserva furos e recortes internos (regra de winding).
        dd = path_data(d["items"])
        if not dd:
            continue
        a = []
        if d.get("fill") is not None:
            a.append(f'fill="{hexcol(d["fill"])}"')
            a.append(f'fill-rule="{"evenodd" if d.get("even_odd") else "nonzero"}"')
            fo = d.get("fill_opacity")
            if fo is not None and fo < 1:
                a.append(f'fill-opacity="{fo:.3f}"')
        else:
            a.append('fill="none"')
        if d.get("color") is not None and d["type"] in ("s", "fs"):
            w = max(0.3, (d.get("width") or 0.5) * M_PER_PT * PX_PER_M)
            a.append(f'stroke="{hexcol(d["color"])}" stroke-width="{w:.2f}"')
            so = d.get("stroke_opacity")
            if so is not None and so < 1:
                a.append(f'stroke-opacity="{so:.3f}"')
        out.append(f'<path {" ".join(a)} d="{dd}"/>')

        for item in d["items"]:
            if item[0] == "re":
                r = item[1]
                x0, y0 = to_m(r.x0, r.y0)
                x1, y1 = to_m(r.x1, r.y1)
                shapes.append({"fill": hexcol(d["fill"]) if d.get("fill") else None,
                               "x_m": round(x0, 3), "y_m": round(y0, 3),
                               "w_m": round(x1 - x0, 3), "h_m": round(y1 - y0, 3)})

    close_to(0)

    # ---- texto: cada span onde o PDF diz, no tamanho que o PDF diz ----
    rotulos = []
    for blk in page.get_text("dict", clip=box)["blocks"]:
        for line in blk.get("lines", []):
            vert = abs(line["dir"][1]) > 0.5
            for sp in line["spans"]:
                txt = sp["text"].strip()
                if not txt:
                    continue
                bb = sp["bbox"]
                cx, cy = to_m((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
                cx, cy = cx * PX_PER_M, cy * PX_PER_M
                size = sp["size"] * M_PER_PT * PX_PER_M
                weight = "bold" if re.search(r"bold|black|heavy", sp["font"], re.I) else "normal"
                rot = f' transform="rotate(-90 {cx:.2f} {cy:.2f})"' if vert else ""
                out.append(
                    f'<text x="{cx:.2f}" y="{cy:.2f}"{rot} fill="#{sp["color"]:06x}" '
                    f'font-family="Helvetica,Arial,sans-serif" font-size="{size:.2f}" '
                    f'font-weight="{weight}" text-anchor="middle" '
                    f'dominant-baseline="central">{esc(txt)}</text>')
                if CODE_RE.fullmatch(txt):
                    rotulos.append({"code": txt, "x_m": round(cx / PX_PER_M, 2),
                                    "y_m": round(cy / PX_PER_M, 2)})

    out.insert(1, "<defs>" + "".join(defs) + "</defs>")
    out.append("</svg>")
    svg = "\n".join(out)
    open(OUT_SVG, "w").write(svg)
    cairosvg.svg2png(bytestring=svg.encode(), write_to=OUT_PNG,
                     output_width=int(W), output_height=int(H),
                     background_color="white")

    json.dump({"meta": {"fonte": PDF, "m_por_pt": round(M_PER_PT, 6),
                        "clip_pt": list(MAP_CLIP), "hall_m": HALL_M},
               "retangulos": shapes, "rotulos": rotulos},
              open(OUT_JSON, "w"), ensure_ascii=False)

    print(f"svg: {OUT_SVG}  png: {OUT_PNG} {int(W)}x{int(H)}  "
          f"retangulos: {len(shapes)}  codigos: {len(rotulos)}")


if __name__ == "__main__":
    sys.exit(main())
