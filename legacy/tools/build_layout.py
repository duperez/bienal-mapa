"""Regulariza a geometria do mapa: o dado extraído vira estrutura, a geometria
final é GERADA — bandas de estande com altura uniforme, ruas uniformes,
corredores verticais uniformes, células contíguas (sem frestas).

Mecânica: um warp global e monotônico dos eixos (piecewise linear), definido
pelos elementos estruturais do miolo (ruas horizontais + corredores verticais),
aplicado a TUDO (estandes, áreas, ruas, marcadores). O que é irregular
(praças, anexo, serviços) acompanha a deformação sem perder posição relativa.
Depois do warp: quantização de sub-linhas e solda de frestas pequenas.

Roda entre build_map.py e build_graph.py (o grafo é regenerado da geometria nova).
"""
import json
from collections import defaultdict

SRC = "data/map.json"

RUA_H = 17.0        # altura da faixa de rua (o original já é uniforme)
BANDA_H = 40.0      # altura idealizada da banda de estandes (original varia 37-42)
CORR_W = 20.0       # largura idealizada dos corredores verticais (original 17-27)
MIOLO_X_MAX = 1015  # miolo = hall principal em grade
WELD_GAP = 5.0      # frestas menores que isso entre células vizinhas fecham
QUANT = 4.0         # borda de célula a menos disso de uma linha de banda gruda


def build_warp(knots):
    """knots: [(old, new)] ordenado -> função monotônica piecewise linear."""
    knots = sorted(knots)
    def f(v):
        if v <= knots[0][0]:
            return v + (knots[0][1] - knots[0][0])
        if v >= knots[-1][0]:
            return v + (knots[-1][1] - knots[-1][0])
        for (o1, n1), (o2, n2) in zip(knots, knots[1:]):
            if o1 <= v <= o2:
                t = (v - o1) / (o2 - o1) if o2 > o1 else 0
                return n1 + t * (n2 - n1)
        return v
    return f


def main():
    m = json.load(open(SRC))

    # ---- fileiras de rua do miolo (K..A), pela banda de y ----
    rows = defaultdict(list)
    for r in m["ruas"]:
        if r["bbox"][0] < MIOLO_X_MAX and r["name"]:
            rows[round(r["bbox"][1] / 10)].append(r)
    row_y0 = sorted(sum(b["bbox"][1] for b in v) / len(v) for v in rows.values())
    assert len(row_y0) == 10, f"esperava 10 fileiras de rua no miolo, achei {len(row_y0)}"

    # eixo Y: primeira rua ancorada onde está; daí pra baixo, passo uniforme
    y_knots = []
    y_new = row_y0[0]
    for y_old in row_y0:
        y_knots.append((y_old, y_new))              # topo da faixa
        y_knots.append((y_old + RUA_H, y_new + RUA_H))  # base da faixa
        y_new += RUA_H + BANDA_H
    fy = build_warp(y_knots)

    # ---- corredores verticais do miolo: clusters de vãos entre faixas ----
    gaps = []
    for v in rows.values():
        v.sort(key=lambda r: r["bbox"][0])
        for a, b in zip(v, v[1:]):
            g = b["bbox"][0] - a["bbox"][2]
            if 5 < g < 60:
                gaps.append(((a["bbox"][2] + b["bbox"][0]) / 2, a["bbox"][2], b["bbox"][0]))
    gaps.sort()
    clusters = []
    for g in gaps:
        if clusters and g[0] - clusters[-1][-1][0] < 12:
            clusters[-1].append(g)
        else:
            clusters.append([g])
    x_knots = []
    for c in clusters:
        cx = sum(p[0] for p in c) / len(c)
        left = sum(p[1] for p in c) / len(c)
        right = sum(p[2] for p in c) / len(c)
        x_knots.append((left, cx - CORR_W / 2))
        x_knots.append((right, cx + CORR_W / 2))
    fx = build_warp(x_knots)
    for knots in (sorted(y_knots), sorted(x_knots)):
        for (o1, n1), (o2, n2) in zip(knots, knots[1:]):
            assert o2 > o1 and n2 > n1, f"warp não-monotônico: {(o1, n1)} -> {(o2, n2)}"

    # ---- aplica o warp a tudo ----
    def warp_shape(s):
        s["bbox"] = [round(fx(s["bbox"][0]), 2), round(fy(s["bbox"][1]), 2),
                     round(fx(s["bbox"][2]), 2), round(fy(s["bbox"][3]), 2)]
        s["poly"] = [[round(fx(x), 2), round(fy(y), 2)] for x, y in s["poly"]]

    for coll in (m["stands"], m["areas"], m["ruas"]):
        for s in coll:
            warp_shape(s)

    # ---- linhas de banda pós-warp (topo/meio/fundo de cada banda) ----
    new_rows = sorted(n for _, n in y_knots[::2])
    band_lines = []
    for a, b in zip(new_rows, new_rows[1:]):
        topo, fundo = a + RUA_H, b
        band_lines += [topo, (topo + fundo) / 2, fundo]

    def quant(v):
        for ln in band_lines:
            if abs(v - ln) < QUANT:
                return ln
        return v

    miolo_stands = [s for s in m["stands"]
                    if s["bbox"][0] < MIOLO_X_MAX and s["cat"] not in ("alameda", "travessa")]
    for s in miolo_stands:
        b = s["bbox"]
        q0, q1 = quant(b[1]), quant(b[3])
        if q1 > q0:
            b[1], b[3] = q0, q1

    # ---- solda de frestas: pares vizinhos na horizontal e na vertical ----
    def weld(axis):
        o0, o1 = (0, 2) if axis == "x" else (1, 3)
        c0, c1 = (1, 3) if axis == "x" else (0, 2)
        for a in miolo_stands:
            for b in miolo_stands:
                if a is b:
                    continue
                ov = min(a["bbox"][c1], b["bbox"][c1]) - max(a["bbox"][c0], b["bbox"][c0])
                span = min(a["bbox"][c1] - a["bbox"][c0], b["bbox"][c1] - b["bbox"][c0])
                if ov < span * 0.5:
                    continue
                gap = b["bbox"][o0] - a["bbox"][o1]
                if 0 < gap < WELD_GAP:
                    mid = round((a["bbox"][o1] + b["bbox"][o0]) / 2, 2)
                    a["bbox"][o1] = mid
                    b["bbox"][o0] = mid

    weld("x")
    weld("y")

    # bboxes soldadas viram o poly de novo (todas as células do miolo são retângulos)
    for s in miolo_stands:
        b = s["bbox"]
        s["poly"] = [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]]

    # ---- células de destaque do miolo (patrocinador/entidade/cultural pequeno):
    # no PDF elas são caixas "3D" menores/deslocadas; dentro de uma banda a
    # semântica é célula da quadra — SEMPRE ocupam a banda: cheia quando
    # sozinha, metades quando duas se empilham (ex. K42/K40, K24/K26) ----
    bands = [(a + RUA_H, b) for a, b in zip(new_rows, new_rows[1:])]

    def band_of(cy):
        for topo, fundo in bands:
            if topo - 3 <= cy <= fundo + 3:
                return topo, fundo
        return None

    # a "célula" de cada banda não encosta nas ruas: usa o y0/y1 TÍPICO (moda)
    # das células expositor da banda como referência, não o vão inteiro
    from collections import Counter
    band_cell = {}
    for topo, fundo in bands:
        ys0, ys1 = Counter(), Counter()
        for s in miolo_stands:
            if s["cat"] != "expositor":
                continue
            scy = (s["bbox"][1] + s["bbox"][3]) / 2
            if topo - 3 <= scy <= fundo + 3:
                ys0[round(s["bbox"][1], 1)] += 1
                ys1[round(s["bbox"][3], 1)] += 1
        if ys0:
            band_cell[(topo, fundo)] = (ys0.most_common(1)[0][0], ys1.most_common(1)[0][0])

    destaque = [s for s in m["stands"]
                if s["cat"] in ("patrocinador", "entidade") and s["bbox"][0] < MIOLO_X_MAX]
    destaque += [a for a in m["areas"]
                 if a["cat"] == "cultural" and a["bbox"][0] < MIOLO_X_MAX
                 and a.get("code") != "TL"  # Travessa tem geometria própria (blocos)
                 and (a["bbox"][2] - a["bbox"][0]) * (a["bbox"][3] - a["bbox"][1]) < 8000]

    for s in destaque:
        b = s["bbox"]
        cy = (b[1] + b[3]) / 2
        band = band_of(cy)
        if not band:
            continue
        topo, fundo = band_cell.get(band, band)
        meio = (topo + fundo) / 2
        # empilhado = outro destaque na mesma banda com forte sobreposição em x
        stacked = [o for o in destaque if o is not s and band_of((o["bbox"][1] + o["bbox"][3]) / 2) == band
                   and min(b[2], o["bbox"][2]) - max(b[0], o["bbox"][0]) >
                       0.5 * min(b[2] - b[0], o["bbox"][2] - o["bbox"][0])]
        if stacked:
            b[1], b[3] = (topo, meio) if cy < meio else (meio, fundo)
        else:
            b[1], b[3] = topo, fundo
        # solda horizontal com células vizinhas (encosta a até 5pt)
        for o in miolo_stands:
            if o is s:
                continue
            ob = o["bbox"]
            if min(b[3], ob[3]) - max(b[1], ob[1]) < (b[3] - b[1]) * 0.5:
                continue
            if 0 < b[0] - ob[2] < WELD_GAP:
                b[0] = ob[2]
            if 0 < ob[0] - b[2] < WELD_GAP:
                b[2] = ob[0]
        s["poly"] = [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]]

    # destaques adjacentes fora de banda (fileira norte: K38/K32) desalinhados
    # pelo 3D: o da direita herda o y do da esquerda quando se encostam
    for a in destaque:
        for b2 in destaque:
            ab, bb = a["bbox"], b2["bbox"]
            if abs(bb[0] - ab[2]) < 2 and 0.5 < abs(bb[1] - ab[1]) < 12 \
                    and min(ab[3], bb[3]) - max(ab[1], bb[1]) > 0.5 * (ab[3] - ab[1]):
                bb[1], bb[3] = ab[1], ab[3]
                b2["poly"] = [[bb[0], bb[1]], [bb[2], bb[1]], [bb[2], bb[3]], [bb[0], bb[3]]]

    # faixas de rua do miolo: gruda no y exato da fileira nova
    for r in m["ruas"]:
        if r["bbox"][0] < MIOLO_X_MAX and r["name"]:
            alvo = min(new_rows, key=lambda y: abs(y - r["bbox"][1]))
            if abs(alvo - r["bbox"][1]) < 6:
                dy = alvo - r["bbox"][1]
                r["bbox"][1] = alvo
                r["bbox"][3] = alvo + RUA_H
                r["poly"] = [[x, y + dy] for x, y in r["poly"]]

    json.dump(m, open(SRC, "w"), ensure_ascii=False, indent=1)
    print(f"layout regularizado: {len(row_y0)} fileiras (banda {BANDA_H}pt), "
          f"{len(clusters)} corredores verticais ({CORR_W}pt)")


if __name__ == "__main__":
    main()
