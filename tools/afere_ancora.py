"""Afere a âncora do desenho contra feições permanentes do prédio (OSM).

O defeito 4 do README diz que a âncora é palpite: o desenho da Bienal ocupa
293 x 149 m dentro de um prédio de 323 x 224 m e a regra em `build_map.ancora`
encosta o bloco mais a noroeste no canto noroeste do prédio, sem prova. Sobram
dezenas de metros sem explicação.

Tentativas anteriores de achar pontos de controle falharam porque o PDF da
Bienal não desenha nenhuma feição permanente do prédio: nem parede, nem pilar,
nem sanitário que casasse com a planta oficial. Este script ataca por outro
lado — as marquises do prédio, que existem no OpenStreetMap (`building=roof`)
e cobrem justamente as entradas. Se os "Acesso Hall" do PDF são as portas sob
essas marquises, os dois conjuntos têm que coincidir depois de aplicada a
âncora; e o quanto NÃO coincidem é a medida do erro.

O resultado é um número, não uma opinião: o deslocamento que alinharia os
acessos às marquises. Se os três acessos pedirem deslocamentos parecidos, o
erro é sistemático e a correção é essa. Se pedirem deslocamentos díspares, a
hipótese de correspondência está errada e o script diz isso.

Não altera nada: só mede.
"""
import json
import math
import sys

sys.path.insert(0, "tools")
from build_map import VENUE  # noqa: E402

CONTROLE = "data/controle-osm.geojson"
GEOJSON = "web/public/data/mapa.geojson"


def quadro():
    """Inverso de build_map.georef: lng/lat -> metros no referencial do prédio.

    Mesma construção do build (origem no canto noroeste, x para leste do
    prédio, y para o sul), para os números saírem comparáveis com o desenho.
    """
    anel = json.load(open(VENUE))["features"][0]["geometry"]["coordinates"][0]
    lat0 = anel[0][1]
    mlat, mlon = 111320.0, 111320.0 * math.cos(math.radians(lat0))
    dx = (anel[1][0] - anel[0][0]) * mlon
    dy = (anel[1][1] - anel[0][1]) * mlat
    n = math.hypot(dx, dy)
    ux, uy = (dx / n, dy / n), (dy / n, -dx / n)

    def bruto(p):
        mx = (p[0] - anel[0][0]) * mlon
        my = (p[1] - anel[0][1]) * mlat
        return (mx * ux[0] + my * ux[1], mx * uy[0] + my * uy[1])

    oeste = min(x for x, y in map(bruto, anel) if abs(y) < 5)

    def para_m(lng, lat):
        x, y = bruto([lng, lat])
        return (x - oeste, y)

    return para_m, [para_m(*p) for p in anel]


def centro(anel, para_m):
    pts = [para_m(*c) for c in anel[:-1]]
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def caixa(anel, para_m):
    pts = [para_m(*c) for c in anel[:-1]]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def main():
    para_m, predio = quadro()
    px = [p[0] for p in predio]
    py = [p[1] for p in predio]
    print(f"prédio (OSM): {max(px) - min(px):.1f} x {max(py) - min(py):.1f} m, "
          f"x {min(px):.1f}..{max(px):.1f}  y {min(py):.1f}..{max(py):.1f}")

    feats = json.load(open(GEOJSON))["features"]
    blocos = [f for f in feats if f["properties"]["kind"] in ("estande", "area")]
    xs, ys = [], []
    for f in blocos:
        x0, y0, x1, y1 = caixa(f["geometry"]["coordinates"][0], para_m)
        xs += [x0, x1]
        ys += [y0, y1]
    print(f"desenho:      {max(xs) - min(xs):.1f} x {max(ys) - min(ys):.1f} m, "
          f"x {min(xs):.1f}..{max(xs):.1f}  y {min(ys):.1f}..{max(ys):.1f}")

    acessos = sorted(
        (para_m(*f["geometry"]["coordinates"]), f["properties"].get("name", ""))
        for f in feats
        if f["properties"]["kind"] == "poi"
        and "acesso" in (f["properties"].get("name") or "").lower()
    )
    print(f"\nacessos no desenho ({len(acessos)}):")
    for (x, y), nome in acessos:
        print(f"  {nome:20s} x={x:7.1f}  y={y:7.1f}")

    marquises = []
    for f in json.load(open(CONTROLE))["features"]:
        anel = f["geometry"]["coordinates"][0]
        x0, y0, x1, y1 = caixa(anel, para_m)
        marquises.append((f["properties"]["osm"], centro(anel, para_m), (x0, y0, x1, y1)))
    print(f"\nmarquises reais ({len(marquises)}):")
    for osm, (cx, cy), (x0, y0, x1, y1) in marquises:
        print(f"  {osm:12s} centro x={cx:7.1f} y={cy:7.1f}   "
              f"extensão {x1 - x0:6.1f} x {y1 - y0:5.1f} m")

    if not acessos:
        print("\nsem acessos no desenho: nada a aferir")
        return 1

    # ---- as quatro orientações possíveis ----
    # O desenho é uma peça de divulgação: não tem norte, não nomeia o prédio e
    # não desenha parede. Nada garante que ele esteja na orientação em que foi
    # colado. As portas do evento, porém, têm que dar para algum lugar — e o
    # prédio real só tem marquise em duas faces. Isso é testável: para cada
    # orientação, procura-se o deslocamento que mais aproxima as portas de uma
    # marquise, sem tirar o desenho de dentro do prédio. Se uma orientação
    # ganhar por larga margem, ela é a resposta.
    dx0, dy0, dx1, dy1 = min(xs), min(ys), max(xs), max(ys)
    marq = [m[2] for m in marquises]

    def perto_marquise(p):
        x, y = p
        return min(
            math.hypot(max(x0 - x, 0, x - x1), max(y0 - y, 0, y - y1))
            for x0, y0, x1, y1 in marq
        )

    portas = [
        para_m(*f["geometry"]["coordinates"])
        for f in feats
        if f["properties"]["kind"] == "poi"
        and (
            f["properties"].get("cat") in ("entrada", "saida")
            or "acesso" in (f["properties"].get("name") or "").lower()
        )
    ]
    print(f"\nportas consideradas: {len(portas)}")

    def vira(p, esp, sul):
        x, y = p
        return (dx0 + dx1 - x if esp else x, dy0 + dy1 - y if sul else y)

    print("\norientação   deslocamento         distância média das portas à marquise")
    ranking = []
    for esp in (False, True):
        for sul in (False, True):
            virados = [vira(p, esp, sul) for p in portas]
            melhor = None
            # folga real dentro do prédio, em passos de 1 m
            for ddx in range(int(min(px) - dx0), int(max(px) - dx1) + 1):
                for ddy in range(int(min(py) - dy0), int(max(py) - dy1) + 1):
                    d = sum(perto_marquise((x + ddx, y + ddy)) for x, y in virados) / len(virados)
                    if melhor is None or d < melhor[0]:
                        melhor = (d, ddx, ddy)
            nome = ("norte" if not sul else "sul") + "/" + ("oeste" if not esp else "leste")
            ranking.append((melhor[0], nome, melhor[1], melhor[2]))
            print(f"  {nome:12s} dx={melhor[1]:+5d} dy={melhor[2]:+5d} m   {melhor[0]:6.1f} m")

    ranking.sort()
    d1, n1, ddx, ddy = ranking[0]
    d2 = ranking[1][0]
    print(f"\nmelhor: {n1} com dx={ddx:+d} dy={ddy:+d} -> portas a {d1:.1f} m da marquise")
    print(f"segunda melhor fica a {d2:.1f} m ({d2 / d1:.1f}x pior)")
    atual = sum(perto_marquise(p) for p in portas) / len(portas)
    print(f"âncora de hoje: portas a {atual:.1f} m da marquise mais próxima")
    if d2 / d1 < 2:
        print("\nas duas primeiras empatam: isto NÃO decide a orientação")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
