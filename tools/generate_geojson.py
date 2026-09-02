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

# ---- âncora geográfica: canto NW do prédio + direção do lado norte ----
venue = json.load(open(VENUE))
ring = venue["features"][0]["geometry"]["coordinates"][0]
# vértices nomeados do polígono OSM (ver README legado): NW, NE, SE, SW...
P_NW = ring[0]   # [-46.6372162, -23.5155046]
P_NE = ring[1]   # [-46.6347654, -23.5156621]

LAT0 = P_NW[1]
M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(LAT0))

# eixo x̂ = direção do lado norte do prédio (em metros)
dx_m = (P_NE[0] - P_NW[0]) * M_PER_DEG_LON
dy_m = (P_NE[1] - P_NW[1]) * M_PER_DEG_LAT
norm = math.hypot(dx_m, dy_m)
UX = (dx_m / norm, dy_m / norm)          # leste do prédio
UY = (UX[1], -UX[0])                     # sul do prédio (perpendicular, y cresce p/ sul)

# o frame já é relativo à parede NW do hall; margem mínima de segurança
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
            feats.append(rect(min(extent), y, max(fim), y + rua_h,
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
                        "name": (directory.get(c["code"]) or "").title() or None,
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

    # ---- áreas ancoradas (praças, alimentação, cultural, serviços) ----
    for a in s.get("areas", []):
        feats.append(rect(a["x_m"], a["y_m"], a["x_m"] + a["w_m"], a["y_m"] + a["h_m"], {
            "kind": "area",
            "cat": a["cat"],
            "code": a.get("code"),
            "name": a.get("nome"),
        }))

    gj = {"type": "FeatureCollection", "features": feats}
    json.dump(gj, open(OUT, "w"), ensure_ascii=False)
    print(f"features: {len(feats)}")


if __name__ == "__main__":
    main()
