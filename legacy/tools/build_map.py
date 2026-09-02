"""Constrói data/map.json a partir do PDF oficial.

Saída:
  stands    — expositor/patrocinador/entidade/alameda, com código (id) casado por texto contido
  areas     — cultural/alimentação/serviço/infra, com nome extraído do texto contido
  ruas      — faixas bege "RUA X" (viram base do grafo depois)
  directory — código -> nome do expositor (lista no rodapé do PDF)
  travessa  — expositores numerados da Travessa Literária (sem estande próprio no mapa)
"""
import json
import re
from collections import defaultdict

import pymupdf

DOC = "reference/mapa-oficial.pdf"
OUT = "data/map.json"

STAND_COLORS = {
    (187, 230, 251): "expositor",
    (250, 238, 19): "patrocinador",
    (255, 242, 0): "patrocinador",
    (179, 127, 184): "entidade",
}
AREA_COLORS = {
    (235, 32, 40): "cultural",
    (237, 33, 36): "cultural",
    (209, 32, 39): "cultural",
    (250, 163, 26): "alimentacao",
    (247, 148, 29): "alimentacao",
    (128, 129, 129): "servico",
    (129, 128, 128): "servico",
    (192, 226, 202): "infra",
}
RUA_COLOR = (198, 177, 152)
TOL = 10

CODE_RE = re.compile(r"^(?:AA|BB|CC|DD|IF|EXT|POD|BK|TI|[A-K])[0-9]{1,3}[A-Z]?$")
LIST_Y = 950           # abaixo disso é a lista de expositores no rodapé
TOP_DECOR_Y = 105      # acima disso é a onda decorativa vermelha do topo
LEGEND = pymupdf.Rect(1075, 285, 1587.4, 490)  # caixa branca real termina em y=485


def rgb255(fill):
    return tuple(round(c * 255) for c in fill) if fill else None


def match_color(rgb, table):
    if rgb is None:
        return None
    for color, cat in table.items():
        if all(abs(a - b) <= TOL for a, b in zip(rgb, color)):
            return cat
    return None


def path_points(drawing):
    pts = []
    for item in drawing["items"]:
        op = item[0]
        if op == "re":
            r = item[1]
            return [[r.x0, r.y0], [r.x1, r.y0], [r.x1, r.y1], [r.x0, r.y1]]
        if op == "l":
            if not pts:
                pts.append([item[1].x, item[1].y])
            pts.append([item[2].x, item[2].y])
        elif op == "c":
            pts.append([item[4].x, item[4].y])
    return pts


def center(bbox):
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def words_inside(words, rect, pad=1.0):
    out = []
    for w in words:
        cx, cy = center(w["bbox"])
        if rect[0] - pad <= cx <= rect[2] + pad and rect[1] - pad <= cy <= rect[3] + pad:
            out.append(w)
    return out


def round2(pts):
    return [[round(x, 2), round(y, 2)] for x, y in pts]


def overlap_frac(a, b):
    """Fração da área de a coberta por b."""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    area = (a[2] - a[0]) * (a[3] - a[1])
    return (ix * iy) / area if area else 0


def split_multi_code(stand, code_words):
    """Divide um retângulo que contém N códigos em N partes no eixo maior.

    A divisa fica no ponto MÉDIO entre os rótulos vizinhos — não em fatias
    iguais: no original os sub-estandes têm larguras diferentes e o rótulo
    fica centrado em cada um (ex. D80 menor que D70)."""
    b = stand["bbox"]
    horizontal = (b[2] - b[0]) >= (b[3] - b[1])
    axis = 0 if horizontal else 1
    ws = sorted(words_inside(code_words, b), key=lambda w: w["bbox"][axis])
    n = len(ws)
    cuts = [b[axis]]
    for w1, w2 in zip(ws, ws[1:]):
        cuts.append((w1["bbox"][axis + 2] + w2["bbox"][axis]) / 2)
    cuts.append(b[axis + 2])
    out = []
    for i, w in enumerate(ws):
        if horizontal:
            nb = [cuts[i], b[1], cuts[i + 1], b[3]]
        else:
            nb = [b[0], cuts[i], b[2], cuts[i + 1]]
        out.append({
            "id": w["text"], "codes": [w["text"]], "cat": stand["cat"],
            "poly": round2([[nb[0], nb[1]], [nb[2], nb[1]], [nb[2], nb[3]], [nb[0], nb[3]]]),
            "bbox": [round(v, 2) for v in nb],
        })
    return out


def main():
    doc = pymupdf.open(DOC)
    page = doc[0]

    all_words = [
        {"text": t, "bbox": [x0, y0, x1, y1]}
        for x0, y0, x1, y1, t, *_ in page.get_text("words")
    ]
    map_words = [w for w in all_words if w["bbox"][1] < LIST_Y
                 and not LEGEND.contains(pymupdf.Point(*center(w["bbox"])))]
    list_words = [w for w in all_words if w["bbox"][1] >= LIST_Y]
    # códigos quebrados em duas linhas no PDF ("K4" / "2" = K42): funde a palavra
    # curta com o dígito imediatamente abaixo, alinhado e colado
    frag_re = re.compile(r"^[A-K][0-9]?$")
    fragments = set()
    composed = []
    for w in map_words:
        if not frag_re.match(w["text"]):
            continue
        wcx = (w["bbox"][0] + w["bbox"][2]) / 2
        for v in map_words:
            if not v["text"].isdigit() or len(v["text"]) > 1:
                continue
            vcx = (v["bbox"][0] + v["bbox"][2]) / 2
            if abs(vcx - wcx) < 4 and -3 <= v["bbox"][1] - w["bbox"][3] < 4:
                novo = w["text"] + v["text"]
                if CODE_RE.match(novo):
                    composed.append({"text": novo, "bbox": [
                        min(w["bbox"][0], v["bbox"][0]), w["bbox"][1],
                        max(w["bbox"][2], v["bbox"][2]), v["bbox"][3]]})
                    fragments.add(id(w))
                    fragments.add(id(v))
                    print(f"código composto: {w['text']}+{v['text']} -> {novo}")
                break

    code_words = [w for w in map_words
                  if CODE_RE.match(w["text"]) and id(w) not in fragments] + composed

    stands, areas, ruas = [], [], []

    for d in page.get_drawings():
        rgb = rgb255(d["fill"])
        r = d["rect"]
        bbox = [round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2)]
        if r.width < 5 or r.height < 5:
            continue
        if LEGEND.contains(pymupdf.Point(*center(bbox))):
            continue
        if r.y0 >= LIST_Y or r.y0 <= TOP_DECOR_Y:
            continue
        cx, cy = center(bbox)
        if cx > 1270 and cy < 300:  # canto sup. direito: onda decorativa e pin
            continue                # (y 300-600 tem banheiro, DD10 e DD20 reais)

        cat = match_color(rgb, STAND_COLORS)
        if cat:
            codes = [w["text"] for w in words_inside(code_words, bbox)]
            stand = {
                "id": codes[0] if len(codes) == 1 else None,
                "codes": codes, "cat": cat,
                "poly": round2(path_points(d)), "bbox": bbox,
            }
            if len(codes) > 1:
                stands.extend(split_multi_code(stand, code_words))
            else:
                stands.append(stand)
            continue

        cat = match_color(rgb, AREA_COLORS)
        if cat:
            inside = words_inside(map_words, bbox)
            # fragmentos decorativos/ícones — mas forma pequena COM texto é real
            # (ex. a faixinha verde "INDIGO" tem só ~190pt²)
            if r.width * r.height < 250 and not inside:
                continue
            inside.sort(key=lambda w: (round(w["bbox"][1]), w["bbox"][0]))
            label = " ".join(w["text"] for w in inside)
            codes = [w["text"] for w in inside if CODE_RE.match(w["text"])]
            # áreas de serviço/alimentação preferem o próprio código IF/EXT/DD
            own = [c for c in codes if c[:2] in ("IF", "EX", "DD")]
            best = own[0] if own else (codes[0] if len(codes) == 1 else None)
            areas.append({
                "cat": cat,
                "code": best,
                "codes": codes,
                "label": label,
                "poly": round2(path_points(d)), "bbox": bbox,
            })
            continue

        if rgb and all(abs(a - b) <= TOL for a, b in zip(rgb, RUA_COLOR)):
            name = " ".join(w["text"] for w in words_inside(map_words, bbox))
            ruas.append({"name": name, "bbox": bbox, "poly": round2(path_points(d))})
            continue

        # área externa (calçada cinza-clara ao redor da Praça/anexo)
        if rgb and all(abs(a - b) <= 6 for a, b in zip(rgb, (198, 199, 200))) \
                and r.width * r.height > 2000:
            areas.append({"cat": "externo", "code": None, "codes": [], "label": "",
                          "poly": round2(path_points(d)), "bbox": bbox})
            continue

        # marcadores: tiras finas verticais coloridas do original (identificam
        # patrocinador/entidade/etc. na ponta ESQUERDA das fileiras) — cor viva.
        # x < 215 evita capturar sombras "3D" de caixas de destaque pelo mapa
        if rgb and 3.5 <= r.width <= 11 and 15 <= r.height <= 85 \
                and (r.x0 + r.x1) / 2 < 215 and max(rgb) - min(rgb) > 55:
            areas.append({"cat": "marcador", "code": None, "codes": [], "label": "",
                          "color": "#%02x%02x%02x" % rgb,
                          "poly": round2(path_points(d)), "bbox": bbox})

    # ---- faixas de rua sintéticas: em algumas colunas o mapa oficial tem só o
    # TEXTO "RUA X" solto, sem a seta bege (inconsistência do original). Sem a
    # faixa, a rua "some" no nosso app — sintetiza uma com a geometria das irmãs:
    # y0/y1 da mesma fileira, x0/x1 da faixa de outra fileira na mesma coluna ----
    def rua_covered(cx, cy):
        return any(r["bbox"][0] - 2 <= cx <= r["bbox"][2] + 2 and
                   r["bbox"][1] - 2 <= cy <= r["bbox"][3] + 2 for r in ruas)

    for w in map_words:
        if w["text"] != "RUA":
            continue
        letra = [v for v in map_words
                 if abs(v["bbox"][1] - w["bbox"][1]) < 3 and
                    0 < v["bbox"][0] - w["bbox"][2] < 8 and len(v["text"]) <= 2]
        if not letra:
            continue
        nome = "RUA " + letra[0]["text"]
        cx = (w["bbox"][0] + letra[0]["bbox"][2]) / 2
        cy = (w["bbox"][1] + w["bbox"][3]) / 2
        if rua_covered(cx, cy):
            continue
        irmas = [r for r in ruas if r["name"] == nome]
        col = [r for r in ruas if r["bbox"][0] <= cx <= r["bbox"][2]]
        if not irmas or not col:
            print(f"AVISO: texto '{nome}' sem faixa e sem referência p/ sintetizar (x={cx:.0f})")
            continue
        # irmã da MESMA fileira do texto (não a primeira por ordem de desenho)
        irmas.sort(key=lambda r: abs((r["bbox"][1] + r["bbox"][3]) / 2 - cy))
        y0, y1 = irmas[0]["bbox"][1], irmas[0]["bbox"][3]
        if not (y0 - 4 <= cy <= y1 + 4):
            print(f"AVISO: texto '{nome}' (y={cy:.0f}) longe da irmã mais próxima "
                  f"(y {y0:.0f}-{y1:.0f}) — faixa sintética pode estar errada")
        col.sort(key=lambda r: abs((r["bbox"][1] + r["bbox"][3]) / 2 - cy))
        x0, x1 = col[0]["bbox"][0], col[0]["bbox"][2]
        nb = [x0, y0, x1, y1]
        ruas.append({"name": nome, "bbox": nb,
                     "poly": round2([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])})
        print(f"faixa sintética: {nome} x {x0:.0f}-{x1:.0f} y {y0:.0f}-{y1:.0f}")

    # camadas duplicadas: azul sem código coberto por estande com código
    coded = [s for s in stands if s["id"]]
    stands = [s for s in stands if s["id"] or not any(
        overlap_frac(s["bbox"], c["bbox"]) > 0.6 for c in coded)]

    # fallback: estande sem código adota código não-usado a até 10pt da borda
    # (alguns rótulos ficam no corredor ao lado do estande, ex. E21)
    used = {c for s in stands for c in s["codes"]}
    for s in stands:
        if s["id"]:
            continue
        b = s["bbox"]
        best, best_d = None, 10.0
        for w in code_words:
            if w["text"] in used:
                continue
            cx, cy = center(w["bbox"])
            dx = max(b[0] - cx, 0, cx - b[2])
            dy = max(b[1] - cy, 0, cy - b[3])
            d = (dx * dx + dy * dy) ** 0.5
            if d < best_d:
                best, best_d = w["text"], d
        if best:
            s["id"] = best
            s["codes"] = [best]
            s["fallback_id"] = True  # código veio de perto, não de dentro do estande —
            used.add(best)           # geometria não é confiável como referência de grid

    # Alameda dos Artistas: cabines TI__ viram estandes sintéticos ao redor do texto.
    # Kerning apertado funde códigos vizinhos ("TI02TI03") — separa em caixas iguais.
    have = {s["id"] for s in stands}
    merged_ti = re.compile(r"^(TI[0-9]{2})(TI[0-9]{2})$")
    ti_words = []
    for w in map_words:
        if CODE_RE.match(w["text"]) and w["text"].startswith("TI"):
            ti_words.append((w["text"], w["bbox"]))
        elif m := merged_ti.match(w["text"]):
            b = w["bbox"]
            mid = (b[0] + b[2]) / 2
            ti_words.append((m.group(1), [b[0], b[1], mid, b[3]]))
            ti_words.append((m.group(2), [mid, b[1], b[2], b[3]]))
    for code, b in ti_words:
        if code in have:
            continue
        pad = 3
        nb = [b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad]
        stands.append({
            "id": code, "codes": [code], "cat": "alameda",
            "poly": round2([[nb[0], nb[1]], [nb[2], nb[1]], [nb[2], nb[3]], [nb[0], nb[3]]]),
            "bbox": [round(v, 2) for v in nb],
        })
        have.add(code)

    # ---- Travessa Literária: blocos tracejados (sem preenchimento, invisíveis à
    # extração por cor) com 48 mini-lugares numerados. Vira uma área nomeada +
    # mini-estandes sintéticos TL01..TL48 pelos números, padrão da Alameda ----
    tl_words = [w for w in map_words
                if 795 < w["bbox"][0] < 920 and 250 < w["bbox"][1] < 345
                and w["text"].isdigit() and 1 <= int(w["text"]) <= 48]
    if tl_words:
        for w in tl_words:
            b = w["bbox"]
            pad = 1.2
            nb = [b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad]
            stands.append({
                "id": f"TL{int(w['text']):02d}", "codes": [], "cat": "travessa",
                "poly": round2([[nb[0], nb[1]], [nb[2], nb[1]], [nb[2], nb[3]], [nb[0], nb[3]]]),
                "bbox": [round(v, 2) for v in nb],
            })
        tx0 = min(w["bbox"][0] for w in tl_words) - 4
        ty0 = min(w["bbox"][1] for w in tl_words) - 4
        tx1 = max(w["bbox"][2] for w in tl_words) + 4
        ty1 = max(w["bbox"][3] for w in tl_words) + 4
        areas.append({
            "cat": "cultural", "code": "TL", "label": "TRAVESSA LITERÁRIA",
            "no_snap": True,  # geometria própria (blocos tracejados), não é célula de grid
            "poly": round2([[tx0, ty0], [tx1, ty0], [tx1, ty1], [tx0, ty1]]),
            "bbox": [round(v, 2) for v in (tx0, ty0, tx1, ty1)],
        })
        achados = {int(w["text"]) for w in tl_words}
        if achados != set(range(1, 49)):
            print("AVISO travessa: números faltando:", sorted(set(range(1, 49)) - achados))
        print(f"travessa literária: {len(tl_words)} mini-lugares + área")

    # ---- descarta fragmentos decorativos (frestas/ícones capturados por engano
    # de cor): sem código/rótulo e finos demais pra ser um estande ou área real ----
    def is_decorative(shape, has_text):
        if has_text or shape.get("cat") in ("marcador", "externo"):
            return False
        b = shape["bbox"]
        w_, h_ = b[2] - b[0], b[3] - b[1]
        # sem texto: ou fresta fina demais, ou pedaço pequeno demais (sombra de
        # destaque "3D" do PDF oficial) pra ser um estande/área de verdade
        return min(w_, h_) < 8 or w_ * h_ < 600
    stands = [s for s in stands if not is_decorative(s, bool(s["id"]))]
    areas = [a for a in areas if not is_decorative(a, bool(a["label"].strip()))]

    # ---- encaixe no grid: caixas de destaque (patrocinador/entidade/cultural/
    # alimentação/serviço) têm altura CUSTOMIZADA por design no PDF oficial
    # (às vezes 1.5x a altura de uma célula, às vezes menos) — não basta
    # encostar numa borda "parecida" solta por aí, senão a caixa fica mais alta
    # ou mais baixa que o vizinho e continua parecendo "fora do grid" (o efeito
    # 3D residual que o usuário reportou). A correção certa: herdar a MESMA
    # linha (altura idêntica) do estande "expositor" mais próximo — nunca uma
    # altura própria — e só então encaixar as colunas nos vizinhos dessa linha.
    GRID_SNAP_AREA_MAX = 8000   # acima disso é área grande de verdade (Praça, Arena) — não encaixa
    ROW_MAX_DIST = 150          # não adota linha de um estande longe demais
    X_TOL = 15

    # estandes com id "de perto" (fallback) podem ser fragmentos/frestas com
    # geometria não confiável — não servem de referência de altura de linha
    ref_stands = [s for s in stands if s["cat"] == "expositor" and not s.get("fallback_id")]

    def nearest(value, options, tol):
        best, best_d = None, tol
        for o in options:
            d = abs(o - value)
            if d < best_d:
                best, best_d = o, d
        return best

    def snap_edge_pair(lo, hi, options, tol):
        """Encaixa cada borda de forma independente — uma borda sem vizinho
        próximo não deve derrubar a outra que tem um encaixe válido."""
        new_lo = nearest(lo, options, tol)
        rest = [o for o in options if o != new_lo] if new_lo is not None else options
        new_hi = nearest(hi, rest, tol)
        new_lo = lo if new_lo is None else new_lo
        new_hi = hi if new_hi is None else new_hi
        return (new_lo, new_hi) if new_hi > new_lo else (lo, hi)

    ROW_Y_WINDOW = 20  # janela de Y pra achar candidatos da MESMA fileira física

    def snap_grid(shape):
        b = shape["bbox"]
        w_, h_ = b[2] - b[0], b[3] - b[1]
        if w_ * h_ >= GRID_SNAP_AREA_MAX or not ref_stands:
            return
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        # em duas etapas: (1) restringe à mesma fileira física por Y — evita
        # confundir com a fileira vizinha (fileiras ficam bem perto verticalmente,
        # então distância 2D pura pode preferir a fileira errada); (2) dentro da
        # fileira certa, desempata por X — evita pegar uma sub-fileira de meia
        # altura só porque calha de ter o mesmo Y numa coluna bem distante
        same_row = [s for s in ref_stands
                    if abs((s["bbox"][1] + s["bbox"][3]) / 2 - cy) < ROW_Y_WINDOW]
        if not same_row:
            return
        # distância ponderada: X domina (acha o vizinho da mesma quadra), mas Y
        # pesa 3x pra não confundir fileiras de meia-altura a ~15pt uma da outra
        # (ex.: CC26 na fileira de baixo quase adotando a linha de DD29 acima)
        def wdist(s):
            sb = s["bbox"]
            dx = (sb[0] + sb[2]) / 2 - cx
            dy = ((sb[1] + sb[3]) / 2 - cy) * 3
            return dx * dx + dy * dy
        row_stand = min(same_row, key=wdist)
        rb = row_stand["bbox"]
        row_dist = (((rb[0] + rb[2]) / 2 - cx) ** 2 + ((rb[1] + rb[3]) / 2 - cy) ** 2) ** 0.5
        if row_dist >= ROW_MAX_DIST:
            return
        # candidato completo primeiro; só aplica se a mudança for a que o encaixe
        # promete (corrigir deslocamento 3D pequeno). Mudança grande de tamanho ou
        # de centro = a forma NÃO pertence a essa linha (banheiros, salas verdes,
        # caixas empilhadas K24/K26...) — auditoria mostrou o snap esmagando elas.
        cand = [b[0], row_stand["bbox"][1], b[2], row_stand["bbox"][3]]
        row_neighbors = [s for s in ref_stands
                          if s["bbox"][1] == cand[1] and s["bbox"][3] == cand[3]]
        x_edges = sorted({round(v, 1) for s in row_neighbors for v in (s["bbox"][0], s["bbox"][2])})
        cand[0], cand[2] = snap_edge_pair(cand[0], cand[2], x_edges, X_TOL)

        nh, nw = cand[3] - cand[1], cand[2] - cand[0]
        ncx, ncy = (cand[0] + cand[2]) / 2, (cand[1] + cand[3]) / 2
        size_ok = 0.72 * h_ <= nh <= 1.38 * h_ and 0.72 * w_ <= nw <= 1.38 * w_
        center_ok = abs(ncx - cx) <= 15 and abs(ncy - cy) <= 15
        if not (size_ok and center_ok):
            return
        b[:] = cand
        shape["snapped"] = True

    for s in stands:
        if s["cat"] in ("patrocinador", "entidade") or s.get("fallback_id"):
            snap_grid(s)
    for a in areas:
        if a["cat"] in ("cultural", "alimentacao", "servico", "infra") and not a.get("no_snap"):
            snap_grid(a)

    # 2D limpo: reconstrói o poly como retângulo — MAS preserva polígonos
    # não-retangulares legítimos (IF10 e K20 são "L" de verdade no original;
    # achatá-los pinta área que não existe). Critério: forma que passou pelo
    # snap ou cujo poly já preenche ~a bbox toda vira retângulo; L fica L.
    def poly_area(pts):
        s = 0.0
        for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
            s += x1 * y2 - x2 * y1
        return abs(s) / 2

    for shape in stands + areas:
        b = shape["bbox"]
        bbox_area = (b[2] - b[0]) * (b[3] - b[1])
        ratio = poly_area(shape["poly"]) / bbox_area if bbox_area else 1
        if shape.get("snapped") or len(shape["poly"]) <= 5 or ratio > 0.92:
            shape["poly"] = round2([[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]])
        shape["bbox"] = [round(v, 2) for v in b]

    # ---- diretório do rodapé: linha física -> entradas iniciadas por código ----
    lines = defaultdict(list)
    for w in list_words:
        lines[round(w["bbox"][3] / 3)].append(w)

    directory, travessa = {}, {}
    num_re = re.compile(r"^[0-9]{1,2}$")
    for _, ws in sorted(lines.items()):
        ws.sort(key=lambda w: w["bbox"][0])
        cur_key, cur_name, cur_kind = None, [], None
        prev_x1 = None

        def flush():
            if cur_key is None or not cur_name:
                return
            name = " ".join(cur_name)
            if cur_kind == "code":
                directory.setdefault(cur_key, name)
            else:
                travessa.setdefault(int(cur_key), name)

        for w in ws:
            t = w["text"]
            gap = None if prev_x1 is None else w["bbox"][0] - prev_x1
            # código só abre entrada nova no começo de coluna (senão "QUADRINHOS A2"
            # seria cortado no "A2"); colunas têm vão bem maior que espaço entre palavras
            starts = (CODE_RE.match(t) and (gap is None or gap > 15)) or \
                     (num_re.match(t) and (gap is None or gap > 6))
            if starts:
                flush()
                cur_key, cur_name = t, []
                cur_kind = "code" if CODE_RE.match(t) else "num"
            elif cur_key is not None:
                if gap is not None and gap > 60:  # pulou para outra coluna sem código
                    flush()
                    cur_key, cur_name, cur_kind = None, [], None
                else:
                    cur_name.append(t)
            prev_x1 = w["bbox"][2]
        flush()

    # ---- sub-áreas para códigos extras: um shape com vários códigos vira o
    # code principal + uma caixinha por código restante (K20 contém K18; o
    # cluster verde contém IF14/IF04/IF15/IF16). A caixinha nasce do rótulo ----
    stand_ids = {s["id"] for s in stands if s["id"]}
    area_codes_set = {a["code"] for a in areas if a["code"]}
    sub_areas = []
    for a in areas:
        for c in a.get("codes", []):
            if c == a["code"] or c in stand_ids or c in area_codes_set:
                continue
            w = next((v for v in code_words if v["text"] == c and
                      a["bbox"][0] - 1 <= (v["bbox"][0] + v["bbox"][2]) / 2 <= a["bbox"][2] + 1 and
                      a["bbox"][1] - 1 <= (v["bbox"][1] + v["bbox"][3]) / 2 <= a["bbox"][3] + 1), None)
            if not w:
                continue
            pad = 6
            nb = [w["bbox"][0] - pad, w["bbox"][1] - pad, w["bbox"][2] + pad, w["bbox"][3] + pad]
            sub_areas.append({"cat": a["cat"], "code": c, "codes": [c], "label": c,
                              "poly": round2([[nb[0], nb[1]], [nb[2], nb[1]],
                                              [nb[2], nb[3]], [nb[0], nb[3]]]),
                              "bbox": [round(v, 2) for v in nb]})
            area_codes_set.add(c)
            print(f"sub-área criada: {c} (dentro de {a['code'] or a['label'][:20]!r})")
    areas.extend(sub_areas)

    # ---- código duplicado entre áreas: o code fica na MENOR (o bloquinho real);
    # a maior (fundo/plataforma, ex. EXT02 cinza) perde o código ----
    by_code = defaultdict(list)
    for a in areas:
        if a["code"]:
            by_code[a["code"]].append(a)
    for c, lst in by_code.items():
        if len(lst) > 1:
            lst.sort(key=lambda a: (a["bbox"][2] - a["bbox"][0]) * (a["bbox"][3] - a["bbox"][1]))
            for a in lst[1:]:
                a["code"] = None
            print(f"código {c} em {len(lst)} áreas — mantido só na menor")

    # ---- painéis instagramáveis: texto rotacionado sem forma própria no PDF ----
    seen_panel = set()
    for w in map_words:
        if "INSTAGRAM" in w["text"].upper():
            key = round(w["bbox"][0] / 30)
            if key in seen_panel:
                continue
            seen_panel.add(key)
            b = w["bbox"]
            nb = [b[0] - 4, b[1] - 4, b[2] + 4, b[3] + 4]
            areas.append({"cat": "infra", "code": None, "codes": [],
                          "label": "PAINEL INSTAGRAMÁVEL",
                          "poly": round2([[nb[0], nb[1]], [nb[2], nb[1]],
                                          [nb[2], nb[3]], [nb[0], nb[3]]]),
                          "bbox": [round(v, 2) for v in nb]})

    # ---- erros do próprio mapa oficial (rótulo impresso 2x; o diretório de
    # expositores confirma o código que deveria estar lá) ----
    for old, novo, picker in [
        ("AA18", "AA20", lambda s: s["bbox"][0]),   # o de MAIOR x é o AA20
        ("K76", "K74", lambda s: s["bbox"][1]),      # o de MAIOR y é o K74
    ]:
        dups = [s for s in stands if s["id"] == old]
        if len(dups) == 2 and novo not in {s["id"] for s in stands}:
            dups.sort(key=picker)
            dups[-1]["id"] = novo
            dups[-1]["codes"] = [novo]
            print(f"typo do mapa oficial corrigido: 2º {old} -> {novo}")

    for s in stands:
        s.pop("fallback_id", None)  # marcador só de build, não precisa ir pro app
    for a in areas:
        a.pop("no_snap", None)
        a.pop("codes", None)
    directory.setdefault("TL", "TRAVESSA LITERÁRIA")

    out = {
        "meta": {
            "event": "28ª Bienal Internacional do Livro de São Paulo",
            "venue": "Pavilhão de Exposições do Distrito Anhembi",
            "dates": "4 a 13 de setembro de 2026",
        },
        "page": [round(page.rect.width, 2), round(page.rect.height, 2)],
        "stands": stands,
        "areas": areas,
        "ruas": ruas,
        "directory": directory,
        "travessa": travessa,
    }
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)

    print(f"stands: {len(stands)} ({sum(1 for s in stands if s['id'])} com id)")
    print(f"areas: {len(areas)}  ruas: {len(ruas)}")
    print(f"directory: {len(directory)}  travessa: {len(travessa)}")
    for s in stands:
        if not s["id"]:
            print("  sem id:", s["cat"], s["bbox"], s["codes"])
    from collections import Counter
    dup = [k for k, n in Counter(s["id"] for s in stands if s["id"]).items() if n > 1]
    if dup:
        print("ATENÇÃO — ids duplicados (mesmo código em 2+ formas):", sorted(dup))
    ids = {s["id"] for s in stands if s["id"]}
    area_codes = {a["code"] for a in areas if a["code"]}
    linked = sum(1 for i in ids if i in directory)
    print(f"stands com nome no diretório: {linked}/{len(ids)}")
    print("códigos do diretório sem forma no mapa:",
          sorted(set(directory) - ids - area_codes)[:30])


if __name__ == "__main__":
    main()
