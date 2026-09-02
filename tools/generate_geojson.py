"""Gerador puro: data/structure.json -> web/public/data/mapa.geojson.

Nenhuma heurística: a geometria nasce das constantes de design + estrutura.
- Fileiras empilhadas norte->sul com banda e rua de altura uniforme.
- Dentro da fileira, quadras em sequência; células contíguas por construção,
  com largura em metros vinda da estrutura; corredores verticais uniformes.
- Coordenadas locais em METROS no frame do prédio, convertidas para lng/lat
  por transformação afim ancorada no canto NW do pavilhão (OSM).
"""
import json
import math

import frame

SRC = "data/structure.json"
VENUE = "data/venue.geojson"
OUT = "web/public/data/mapa.geojson"

# ---- âncora geográfica: canto NW REAL do prédio + direção do lado norte ----
venue = json.load(open(VENUE))
ring = venue["features"][0]["geometry"]["coordinates"][0]
# ring[0]/ring[1] são dois vértices do lado norte (definem a direção), mas
# ring[0] NÃO é o canto NW: o prédio segue ~66m a oeste dele. O canto real é
# o vértice mais a oeste dentre os que estão sobre o lado norte (y≈0).
P_REF = ring[0]
P_NE = ring[1]

LAT0 = P_REF[1]
M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(LAT0))

# eixo x̂ = direção do lado norte do prédio (em metros)
dx_m = (P_NE[0] - P_REF[0]) * M_PER_DEG_LON
dy_m = (P_NE[1] - P_REF[1]) * M_PER_DEG_LAT
norm = math.hypot(dx_m, dy_m)
UX = (dx_m / norm, dy_m / norm)          # leste do prédio
UY = (UX[1], -UX[0])                     # sul do prédio (perpendicular, y cresce p/ sul)


def _frame_of(p):
    mx = (p[0] - P_REF[0]) * M_PER_DEG_LON
    my = (p[1] - P_REF[1]) * M_PER_DEG_LAT
    return (mx * UX[0] + my * UX[1], mx * UY[0] + my * UY[1])


_west_x = min(x for x, y in (_frame_of(p) for p in ring) if abs(y) < 5)
P_NW = [P_REF[0] + _west_x * UX[0] / M_PER_DEG_LON,
        P_REF[1] + _west_x * UX[1] / M_PER_DEG_LAT]

# margem interna mínima a partir da parede NW real
ORIGIN_OFFSET_M = (2.0, 2.0)


def to_lnglat(x_m: float, y_m: float):
    ex = x_m + ORIGIN_OFFSET_M[0]
    ey = y_m + ORIGIN_OFFSET_M[1]
    mx = ex * UX[0] + ey * UY[0]
    my = ex * UX[1] + ey * UY[1]
    return [round(P_NW[0] + mx / M_PER_DEG_LON, 7),
            round(P_NW[1] + my / M_PER_DEG_LAT, 7)]


def rect(x0, y0, x1, y1, props):
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "Polygon", "coordinates": [[
            to_lnglat(x0, y0), to_lnglat(x1, y0), to_lnglat(x1, y1),
            to_lnglat(x0, y1), to_lnglat(x0, y0),
        ]]},
    }


def main():
    s = json.load(open(SRC))
    C = s["meta"]["constantes"]
    banda_h = C["banda_m"]
    rua_h = C["rua_m"]
    cel_prof = C["celula_profundidade_m"]
    corr_w = C["corredor_vertical_m"]
    respiro = C["respiro_m"]
    directory = s["directory"]

    # eixo y pelas ruas do frame compartilhado (idêntico ao warp do importador)
    _, ruas_y_m = frame.build_y_warp(s["ruas_y_pt"], banda_h, rua_h)
    nomes_ruas = ["K", "J", "H", "G", "F", "E", "D", "C", "B", "A"]
    rua_y_m = {n: ruas_y_m[i] for i, n in enumerate(nomes_ruas)}

    # malha de circulação fechada: no pavilhão real corredor não morre no nada.
    # As ruas horizontais estendem até um anel perimetral conservador (nada de
    # atalhos inventados — só completar a circulação que fisicamente existe).
    todas_q = [q for f in s["fileiras"] for q in f["quadras"]]
    WEST = min(q["offset_m"] for q in todas_q) - corr_w
    EAST = max(q["offset_m"] + sum(col["largura_m"] for col in q["colunas"])
               for q in todas_q) + corr_w

    feats = []
    for fileira in s["fileiras"]:
        banda = fileira["banda"]
        eh_rua_banda = len(banda) == 2  # "KJ", "JH"... têm rua acima
        if banda == "norte":
            y = rua_y_m["K"] - banda_h
        elif eh_rua_banda:
            y = rua_y_m[banda[0]]
        else:  # "Asul"
            y = rua_y_m["A"]
        quadras = fileira["quadras"]
        extent = [q["offset_m"] for q in quadras]
        fim = [q["offset_m"] + sum(col["largura_m"] for col in q["colunas"]) for q in quadras]

        if eh_rua_banda or banda.endswith("sul"):
            rua_nome = banda[0]
            feats.append(rect(WEST, y, EAST, y + rua_h,
                              {"kind": "rua", "name": f"RUA {rua_nome}"}))
            y += rua_h

        top = y + (banda_h - cel_prof) / 2 if eh_rua_banda else y + respiro
        meio = top + cel_prof / 2
        for qi, q in enumerate(quadras):
            x = q["offset_m"]
            qx0 = x
            for col in q["colunas"]:
                w = col["largura_m"]
                for c in col["celulas"]:
                    if c["lado"] == "cheia":
                        y0, y1 = top, top + cel_prof
                    elif c["lado"] == "norte":
                        y0, y1 = top, meio
                    else:
                        y0, y1 = meio, top + cel_prof
                    feats.append(rect(x, y0, x + w, y1, {
                        "kind": "estande",
                        "cat": c["cat"],
                        "code": c["code"],
                        "name": frame.title_pt(directory.get(c["code"])) or None,
                    }))
                x += w
            feats.append(rect(qx0, top, x, top + cel_prof,
                              {"kind": "quadra", "id": q["id"]}))
            # corredor vertical: o vão real entre esta quadra e a próxima.
            # Vãos largos (>12m) são áreas especiais futuras, não corredor.
            if qi + 1 < len(quadras):
                prox = quadras[qi + 1]["offset_m"]
                if 0.5 < prox - x <= 12.0:
                    feats.append(rect(x, y, prox, y + banda_h,
                                      {"kind": "rua", "name": None}))

    # anel perimetral lateral: liga as pontas de todas as ruas horizontais
    y_topo = rua_y_m["K"] - banda_h
    y_fundo = rua_y_m["A"] + rua_h + banda_h
    feats.append(rect(WEST - corr_w, y_topo, WEST, y_fundo, {"kind": "rua", "name": None}))
    feats.append(rect(EAST, y_topo, EAST + corr_w, y_fundo, {"kind": "rua", "name": None}))

    # ---- áreas ancoradas (praças, alimentação, cultural, serviços) ----
    for a in s.get("areas", []):
        feats.append(rect(a["x_m"], a["y_m"], a["x_m"] + a["w_m"], a["y_m"] + a["h_m"], {
            "kind": "area",
            "cat": a["cat"],
            "code": a.get("code"),
            "name": a.get("nome"),
            # rótulo de área maior ganha a disputa de espaço (sort-key no app)
            "peso": round(a["w_m"] * a["h_m"], 1),
        }))

    # ---- estandes ancorados: anexo (AA-DD), Alameda (TI), Travessa (TL),
    # células soltas do miolo ----
    travessa = s.get("travessa", {})

    def nome_de(code):
        if code and code.startswith("TL"):
            n = travessa.get(str(int(code[2:])))
            return frame.title_pt(n) if n else None
        n = directory.get(code)
        return frame.title_pt(n) if n else None

    # piso da tenda do anexo: os ancorados de lá não podem flutuar no vazio
    anexo = [a for a in s.get("ancorados", []) if a["x_m"] > 255]
    if anexo:
        ax0 = min(a["x_m"] for a in anexo) - 4
        ay0 = min(a["y_m"] for a in anexo) - 4
        ax1 = max(a["x_m"] + a["w_m"] for a in anexo) + 4
        ay1 = max(a["y_m"] + a["h_m"] for a in anexo) + 4
        feats.append(rect(ax0, ay0, ax1, ay1, {"kind": "piso", "name": None}))

    for a in s.get("ancorados", []):
        feats.append(rect(a["x_m"], a["y_m"], a["x_m"] + a["w_m"], a["y_m"] + a["h_m"], {
            "kind": "estande",
            "cat": a["cat"],
            "code": a["code"],
            "name": nome_de(a["code"]),
            # cabines minúsculas (Travessa, Alameda, fileira AA): rótulo só no
            # zoom bem fechado, senão viram poluição quadriculada
            "mini": a["w_m"] < 2.5 or a["h_m"] < 2.5,
        }))

    # ruas do anexo (AA-DD)
    for r in s.get("ruas_anexo", []):
        feats.append(rect(r["x_m"], r["y_m"], r["x_m"] + r["w_m"], r["y_m"] + r["h_m"],
                          {"kind": "rua", "name": r["nome"]}))

    gj = {"type": "FeatureCollection", "features": feats}
    json.dump(gj, open(OUT, "w"), ensure_ascii=False)
    print(f"features: {len(feats)}")


if __name__ == "__main__":
    main()
