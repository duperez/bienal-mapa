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

# margem interna: o conteúdo não nasce colado na parede
ORIGIN_OFFSET_M = (6.0, 6.0)


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

    feats = []
    y = 0.0
    for fileira in s["fileiras"]:
        banda = fileira["banda"]
        eh_rua_banda = len(banda) == 2  # "KJ", "JH"... têm rua acima
        if eh_rua_banda or banda.endswith("sul"):
            # faixa de rua acima desta banda (nome = rua de cima)
            rua_nome = banda[0]
            largura_total = sum(
                sum(col["largura_m"] for col in q["colunas"]) for q in fileira["quadras"]
            ) + corr_w * (len(fileira["quadras"]) - 1)
            feats.append(rect(0, y, largura_total, y + rua_h,
                              {"kind": "rua", "name": f"RUA {rua_nome}"}))
            y += rua_h

        top = y + (banda_h - cel_prof) / 2 if eh_rua_banda else y + respiro
        meio = top + cel_prof / 2
        x = 0.0
        for q in fileira["quadras"]:
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
            x += corr_w
        y += banda_h

    gj = {"type": "FeatureCollection", "features": feats}
    json.dump(gj, open(OUT, "w"), ensure_ascii=False)
    print(f"features: {len(feats)}")


if __name__ == "__main__":
    main()
