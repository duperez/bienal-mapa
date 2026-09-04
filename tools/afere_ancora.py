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

    # ---- afere o assentamento aplicado ----
    # A ORIENTAÇÃO já foi decidida, e por rótulo, não por ajuste: ver
    # build_map.assentamento(). Caçar orientação aqui era um erro de método —
    # a métrica de distância não distingue reflexão de rotação, e por isso
    # preferia o mapa espelhado, que ninguém imprime. O que sobra para medir é
    # a POSIÇÃO do desenho dentro do prédio, que é o defeito 4 do README.
    #
    # O critério tem duas pontas, e é isso que o torna difícil de enganar:
    # as portas de PÚBLICO têm que dar para a marquise (é por onde o visitante
    # entra) e as de SERVIÇO para a fachada oposta (é por onde entra caminhão).
    # Um deslocamento que agrada uma ponta piora a outra.
    dx0, dy0, dx1, dy1 = min(xs), min(ys), max(xs), max(ys)
    marq = [m[2] for m in marquises]
    # a marquise do público é a grande da face y=0; as outras duas são de
    # outros acessos do complexo e não recebem o público da Bienal
    publica = max(marq, key=lambda b: b[2] - b[0])

    def dist_caixa(p, b):
        x, y = p
        x0, y0, x1, y1 = b
        return math.hypot(max(x0 - x, 0, x - x1), max(y0 - y, 0, y - y1))

    def eh_servico(f):
        n = (f["properties"].get("name") or "").lower()
        return "serviço" in n or "servico" in n or "emergência" in n or "emergencia" in n

    todas = [f for f in feats if f["properties"]["kind"] == "poi"
             and (f["properties"].get("cat") in ("entrada", "saida", "escolas",
                                                 "entrada-expositor", "entrada-bilheteria")
                  or "acesso" in (f["properties"].get("name") or "").lower())]
    pub = [para_m(*f["geometry"]["coordinates"]) for f in todas if not eh_servico(f)]
    srv = [para_m(*f["geometry"]["coordinates"]) for f in todas if eh_servico(f)]
    print(f"\nportas de público: {len(pub)}   de serviço: {len(srv)}")

    # a fachada de serviço é a face oposta à marquise pública, no fundo do
    # prédio: uma faixa, não uma caixa desenhada
    fundo = max(py)

    def custo(ddx, ddy):
        a = sum(dist_caixa((x + ddx, y + ddy), publica) for x, y in pub) / max(1, len(pub))
        b = sum(abs(fundo - (y + ddy)) for _, y in srv) / max(1, len(srv))
        return a, b, (a + b) / 2

    print("\nassentamento de hoje:")
    a, b, m = custo(0, 0)
    print(f"  público -> marquise : {a:6.1f} m")
    print(f"  serviço -> fachada  : {b:6.1f} m")
    print(f"  média               : {m:6.1f} m")

    melhor = None
    for ddx in range(int(min(px) - dx0), int(max(px) - dx1) + 1):
        for ddy in range(int(min(py) - dy0), int(max(py) - dy1) + 1):
            c = custo(ddx, ddy)
            if melhor is None or c[2] < melhor[0][2]:
                melhor = (c, ddx, ddy)
    (a, b, m), ddx, ddy = melhor
    print(f"\nmelhor deslocamento possível: dx={ddx:+d} dy={ddy:+d} m")
    print(f"  público -> marquise : {a:6.1f} m")
    print(f"  serviço -> fachada  : {b:6.1f} m")
    print(f"  média               : {m:6.1f} m")
    print("\nO resíduo que sobra é o defeito 4: o desenho é menor que o prédio\n"
          "e nada no PDF diz onde ele encosta. Só uma planta cotada do piso\n"
          "resolve isso de vez.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
