"""Extrai estandes, áreas e textos do PDF oficial da Bienal para reference/extracao.json.

Categorias por cor de preenchimento (legenda do mapa oficial):
  azul (187,230,251)  -> expositor
  amarelo             -> patrocinador
  roxo                -> entidade
  vermelho            -> atividade cultural
  laranja             -> alimentação
  verde claro         -> infra
  bege (198,177,152)  -> faixa de rua (RUA A..K)
"""
import json
import re
from collections import defaultdict

import pymupdf

DOC = "reference/mapa-oficial.pdf"
OUT = "reference/extracao.json"

CATEGORIES = {
    "expositor": [(187, 230, 251)],
    "rua": [(198, 177, 152)],
    "infra": [(192, 226, 202)],
    "alimentacao": [(250, 163, 26), (247, 148, 29)],
    "patrocinador": [(250, 238, 19), (255, 242, 0)],
    "cultural": [(235, 32, 40), (237, 33, 36), (209, 32, 39)],
}
TOLERANCE = 10


def close(a, b):
    return all(abs(x - y) <= TOLERANCE for x, y in zip(a, b))


def categorize(fill):
    if fill is None:
        return None
    rgb = tuple(round(c * 255) for c in fill)
    for cat, colors in CATEGORIES.items():
        if any(close(rgb, c) for c in colors):
            return cat
    return None


def path_points(drawing):
    """Extrai vértices de um drawing (rects e polilinhas)."""
    pts = []
    for item in drawing["items"]:
        op = item[0]
        if op == "re":
            r = item[1]
            return [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)], "rect"
        if op == "l":
            p1, p2 = item[1], item[2]
            if not pts:
                pts.append((p1.x, p1.y))
            pts.append((p2.x, p2.y))
        elif op == "c":
            # curva: aproxima pelo ponto final (cantos arredondados etc.)
            pts.append((item[4].x, item[4].y))
    return pts, "poly"


def main():
    doc = pymupdf.open(DOC)
    page = doc[0]

    shapes = []
    ops_stats = defaultdict(int)
    for d in page.get_drawings():
        cat = categorize(d["fill"])
        if cat is None:
            continue
        r = d["rect"]
        if r.width < 4 or r.height < 4:  # descarta fragmentos decorativos
            continue
        pts, kind = path_points(d)
        shapes.append({
            "category": cat,
            "kind": kind,
            "bbox": [round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2)],
            "points": [[round(x, 2), round(y, 2)] for x, y in pts],
        })
        ops_stats[(cat, kind)] += 1

    words = []
    for x0, y0, x1, y1, text, *_ in page.get_text("words"):
        words.append({"text": text, "bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)]})

    json.dump({"page": [page.rect.width, page.rect.height], "shapes": shapes, "words": words},
              open(OUT, "w"), ensure_ascii=False)

    # ---- estatísticas ----
    print("formas por (categoria, tipo):", dict(ops_stats))

    code_re = re.compile(r"^(?:[A-K]|AA|BB|CC|DD|IF|EXT|POD)[0-9]{1,3}[A-Z]?$")
    blues = [s for s in shapes if s["category"] == "expositor"]
    code_words = [w for w in words if code_re.match(w["text"])]
    print(f"expositores: {len(blues)} | palavras-código no doc: {len(code_words)}")

    def inside(w, s):
        wx = (w["bbox"][0] + w["bbox"][2]) / 2
        wy = (w["bbox"][1] + w["bbox"][3]) / 2
        b = s["bbox"]
        return b[0] - 1 <= wx <= b[2] + 1 and b[1] - 1 <= wy <= b[3] + 1

    matched, empty, multi = 0, [], []
    used = set()
    for s in blues:
        inside_codes = [w["text"] for w in code_words if inside(w, s)]
        if len(inside_codes) == 1:
            matched += 1
            used.add(inside_codes[0])
        elif not inside_codes:
            empty.append(s["bbox"])
        else:
            multi.append((s["bbox"], inside_codes))
            used.update(inside_codes)
    print(f"azuis com 1 código: {matched} | sem código: {len(empty)} | com vários: {len(multi)}")
    if empty[:5]:
        print("exemplos sem código:", empty[:5])
    if multi[:5]:
        print("exemplos com vários:", [m[1] for m in multi[:5]])

    # códigos que aparecem no mapa (y < 1010, acima da lista de expositores)
    map_codes = {w["text"] for w in code_words if w["bbox"][1] < 1010}
    print(f"códigos na área do mapa: {len(map_codes)} | não casados com azul: {sorted(map_codes - used)[:40]}")


if __name__ == "__main__":
    main()
