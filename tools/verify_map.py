"""Teste de aceite VETORIAL: mapa.geojson vs PDF oficial.

Mede o que importa — geometria — em vez de pixels. Para cada forma preenchida
do PDF que o build deveria ter transcrito, procura a feature correspondente no
GeoJSON e compara área, IoU e deriva de centroide em centímetros.

Por que vetorial: o teste raster anterior punia antialiasing e formas de 2 px
(a categoria "entidade" dava IoU 0,09 sendo geometricamente perfeita) e era
enganado por logotipos desenhados por cima. Aqui, 1,0 é 1,0.

Uso:
    python tools/verify_map.py            # compara com o baseline
    python tools/verify_map.py --aceitar  # grava o baseline atual
"""
import json
import math
import sys

import pymupdf
from shapely.geometry import Polygon
from shapely.strtree import STRtree

sys.path.insert(0, "tools")
from build_map import (MAP_CLIP, LEGENDA, TRAVESSA, VENUE, ancora, classificar,
                       extrair, ring_area)  # noqa: E402

GEOJSON = "web/public/data/mapa.geojson"
BASELINE = "data/aceite-baseline.json"
TOL_IOU = 0.98        # forma considerada fiel
TOL_DERIVA_CM = 5.0   # deriva máxima de centroide aceitável


def inverso(ox=0.0, oy=0.0):
    """lng/lat -> metros no frame do desenho (inverso exato do build).

    (ox, oy) é a âncora de build_map.ancora(): sem ela o teste mede num frame
    deslocado do que o build gravou e reprova tudo.
    """
    ring = json.load(open(VENUE))["features"][0]["geometry"]["coordinates"][0]
    lat0 = ring[0][1]
    mlat, mlon = 111320.0, 111320.0 * math.cos(math.radians(lat0))
    dx = (ring[1][0] - ring[0][0]) * mlon
    dy = (ring[1][1] - ring[0][1]) * mlat
    n = math.hypot(dx, dy)
    ux, uy = (dx / n, dy / n), (dy / n, -dx / n)

    def frame(p):
        mx = (p[0] - ring[0][0]) * mlon
        my = (p[1] - ring[0][1]) * mlat
        return (mx * ux[0] + my * ux[1], mx * uy[0] + my * uy[1])

    west = min(x for x, y in map(frame, ring) if abs(y) < 5)
    nw = [ring[0][0] + west * ux[0] / mlon, ring[0][1] + west * ux[1] / mlat]

    def to_m(lng, lat):
        mx = (lng - nw[0]) * mlon
        my = (lat - nw[1]) * mlat
        return (mx * ux[0] + my * ux[1] + ox, mx * uy[0] + my * uy[1] + oy)

    return to_m


def limpa(p):
    return p if p.is_valid else p.buffer(0)


TOL_MODULO_CM = 18.0   # desvio médio ao módulo de 1 m; aleatório seria 25 cm


def confere_escala(feats, to_m):
    """A escala do desenho ainda cai em cima do módulo de 1 m dos estandes?

    Guarda contra o erro que já custou duas reescritas: escala escolhida por
    palpite. Se ESCALA_M_PT sair do lugar, os lados param de bater em números
    inteiros e o desvio médio sobe na direção dos 25 cm do puro acaso.
    Ver tools/calibra.py para a medida completa.
    """
    lados = []
    for f in feats:
        if f["properties"].get("kind") not in ("estande", "area"):
            continue
        if f["geometry"]["type"] != "Polygon":
            continue
        pts = [to_m(*c) for c in f["geometry"]["coordinates"][0]]
        for a, b in zip(pts, pts[1:]):
            L = math.hypot(a[0] - b[0], a[1] - b[1])
            if 0.5 < L < 40.0:
                lados.append(L)
    if not lados:
        print("escala: sem lados para medir")
        return False
    d = 100 * sum(min(L % 1.0, 1 - L % 1.0) for L in lados) / len(lados)
    ok = d <= TOL_MODULO_CM
    print(f"\nescala: desvio ao módulo de 1 m = {d:.1f} cm em {len(lados)} lados "
          f"({'OK' if ok else 'FORA'}; acaso = 25,0 cm)")
    return ok


def confere_dentro(feats, to_m):
    """Nada desenhado pode cair fora do prédio.

    É a consequência checável da âncora (build_map.ancora). Enquanto a posição
    real do desenho dentro do pavilhão for desconhecida, esta é a única
    afirmação que dá para cobrar: se um bloco aparece atravessando a parede no
    app, ou a âncora escorregou ou a janela de leitura voltou a cortar planta.
    """
    from shapely.geometry import Polygon

    ring = json.load(open(VENUE))["features"][0]["geometry"]["coordinates"][0]
    pred = limpa(Polygon([to_m(*c) for c in ring]))
    fora = []
    for f in feats:
        p = f["properties"]
        if p.get("kind") not in ("estande", "area", "piso"):
            continue
        if f["geometry"]["type"] != "Polygon":
            continue
        g = limpa(Polygon([to_m(*c) for c in f["geometry"]["coordinates"][0]]))
        if g.is_empty:
            continue
        vaza = g.difference(pred).area
        if vaza > 0.5:
            fora.append((p.get("code") or p.get("name") or p["kind"],
                         round(100 * vaza / g.area)))
    print(f"\nfora do prédio: {len(fora)} blocos")
    for nome, pct in sorted(fora, key=lambda t: -t[1])[:8]:
        print(f"    {nome} ({pct}% fora)")
    return not fora


def confere_vias(feats, to_m, modelo):
    """As vias são derivadas, não transcritas — então precisam de teste próprio.

    Três perguntas: toda rua nomeada no PDF virou via? nenhuma via passa por
    dentro de um bloco? todo estande encosta na circulação (senão é estande
    inalcançável, e aí o mapa mente)?
    """
    from shapely.geometry import LineString, shape
    from shapely.ops import unary_union

    def em_metros(g):
        c = g["coordinates"]
        linhas = [c] if g["type"] == "LineString" else c
        return unary_union([LineString([to_m(*p) for p in l]) for l in linhas])

    setas = {f["properties"]["name"].upper() for f in feats
             if f["properties"]["kind"] == "rua" and f["properties"].get("name")}
    vias = {f["properties"]["name"].upper(): em_metros(f["geometry"])
            for f in feats if f["properties"]["kind"] == "via"}
    faltando = sorted(setas - set(vias))

    # só o que o visitante procura precisa ser alcançável; sala técnica
    # embutida em outro bloco não tem porta para o corredor e nem deveria ter
    blocos = [g for p, g in modelo if p["kind"] in ("estande", "area")
              and (p.get("code") or p.get("name"))]
    circ = unary_union([g for p, g in modelo if p["kind"] == "circulacao"])

    # Erosão de 30 cm antes de acusar: uma via que corre rente ao bloco é
    # colinear com a borda dele, e a interseção crua devolve o comprimento
    # inteiro do contato. Isso é tangência, que é o comportamento desejado —
    # travessia de verdade entra pelo miolo do bloco e sobrevive à erosão.
    ROCE = 0.3
    invasoes = []
    for nome, linha in vias.items():
        for g in blocos:
            miolo = g.buffer(-ROCE)
            if not miolo.is_empty and linha.intersection(miolo).length > 0.5:
                invasoes.append(nome)
                break

    ilhados = [(f'{p["kind"]}/{p.get("cat")}/{p.get("code")}/{p.get("name")}',
                [round(v, 1) for v in g.centroid.coords[0]], round(g.distance(circ), 1))
               for p, g in modelo if p["kind"] in ("estande", "area")
               and (p.get("code") or p.get("name")) and g.distance(circ) > 0.6]

    print(f"\nvias: {len(vias)} ({len(setas)} nomeadas no PDF)")
    if faltando:
        print(f"  rua do PDF sem via: {', '.join(faltando)}")
    if invasoes:
        print(f"  via passando por dentro de bloco: {', '.join(sorted(invasoes))}")
    print(f"  blocos sem circulação ao lado: {len(ilhados)}/{len(blocos)}")
    for i in ilhados[:8]:
        print(f"    {i[0]} em {i[1]} m, a {i[2]} m da circulação")
    return not faltando and not invasoes and not ilhados


def main():
    box = pymupdf.Rect(*MAP_CLIP)
    page = pymupdf.open("reference/mapa-oficial.pdf")[0]
    formas, m_per_pt = extrair(page, box)

    lx0, ly0 = ((LEGENDA[0] - box.x0) * m_per_pt, (LEGENDA[1] - box.y0) * m_per_pt)
    lx1, ly1 = ((LEGENDA[2] - box.x0) * m_per_pt, (LEGENDA[3] - box.y0) * m_per_pt)

    tv0, tv1 = ((TRAVESSA[0] - box.x0) * m_per_pt, (TRAVESSA[1] - box.y0) * m_per_pt)
    tv2, tv3 = ((TRAVESSA[2] - box.x0) * m_per_pt, (TRAVESSA[3] - box.y0) * m_per_pt)

    # o que o PDF manda existir, pela MESMA regra que o build usa
    esperado = []
    for f in formas:
        ext = max(f["aneis"], key=lambda r: abs(ring_area(r)))
        area = abs(ring_area(ext))
        if area < 0.5 or all(lx0 <= x <= lx1 and ly0 <= y <= ly1 for x, y in ext):
            continue
        xs = [p[0] for p in ext]
        ys = [p[1] for p in ext]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        na_tv = tv0 <= cx <= tv2 and tv1 <= cy <= tv3
        kind, cat = classificar(f["cor"], ext, area, na_tv)
        if kind is None or kind == "poi":   # POI vira Point, não polígono
            continue
        buracos = [r for r in f["aneis"] if r is not ext and abs(ring_area(r)) > 1.0]
        esperado.append((cat or kind, limpa(Polygon(ext, buracos))))

    to_m = inverso(*ancora(formas, box, m_per_pt))
    feats = json.load(open(GEOJSON))["features"]
    modelo = []
    for f in feats:
        if f["geometry"]["type"] != "Polygon":
            continue
        anel = [to_m(*p) for p in f["geometry"]["coordinates"][0]]
        buracos = [[to_m(*p) for p in r] for r in f["geometry"]["coordinates"][1:]]
        modelo.append((f["properties"], limpa(Polygon(anel, buracos))))

    geoms = [g for _, g in modelo]
    tree = STRtree(geoms)

    res = {}
    derivas = []
    orfaos = []
    for cat, alvo in esperado:
        cand = tree.query(alvo)
        melhor, iou = None, 0.0
        for i in cand:
            g = geoms[i]
            u = alvo.union(g).area
            if u <= 0:
                continue
            v = alvo.intersection(g).area / u
            if v > iou:
                iou, melhor = v, g
        # bloco subdividido em N células: a união das células é que deve casar
        if iou < TOL_IOU and cand.size:
            partes = [geoms[i] for i in cand if alvo.contains(geoms[i].centroid)]
            if partes:
                from shapely.ops import unary_union
                u = unary_union(partes)
                v = alvo.intersection(u).area / alvo.union(u).area
                if v > iou:
                    iou, melhor = v, u
        d = res.setdefault(cat, {"total": 0, "fiel": 0})
        d["total"] += 1
        if iou >= TOL_IOU:
            d["fiel"] += 1
            derivas.append(alvo.centroid.distance(melhor.centroid) * 100)
        else:
            orfaos.append((cat, round(iou, 3),
                           [round(v, 1) for v in alvo.centroid.coords[0]]))

    print(f"{'categoria':14s} {'fiéis':>12s}   cobertura")
    atual = {}
    for cat in sorted(res):
        d = res[cat]
        cob = d["fiel"] / d["total"]
        atual[cat] = round(cob, 4)
        print(f"  {cat:12s} {d['fiel']:5d}/{d['total']:<5d}   {cob:6.1%}")

    dmax = max(derivas) if derivas else 0.0
    atual["_deriva_cm"] = round(dmax, 2)
    print(f"\nderiva máxima de centroide: {dmax:.2f} cm "
          f"({'OK' if dmax <= TOL_DERIVA_CM else 'ALTA'})")
    if orfaos:
        print(f"formas do PDF sem par fiel: {len(orfaos)}")
        for o in sorted(orfaos, key=lambda o: o[1])[:8]:
            print(f"   {o[0]:12s} IoU {o[1]:.3f}  em {o[2]} m")

    vias_ok = confere_vias(feats, to_m, modelo)
    escala_ok = confere_escala(feats, to_m)
    dentro_ok = confere_dentro(feats, to_m)

    if "--aceitar" in sys.argv:
        json.dump(atual, open(BASELINE, "w"), indent=1)
        print(f"baseline gravado em {BASELINE}")
        return 0

    try:
        base = json.load(open(BASELINE))
    except OSError:
        print("sem baseline — rode com --aceitar")
        return 0

    ok = True
    for cat, v in atual.items():
        ref = base.get(cat)
        if ref is None:
            continue
        if cat == "_deriva_cm":
            if v > ref + 1.0:
                print(f"REGREDIU deriva: {v} cm (era {ref})")
                ok = False
        elif v < ref - 0.01:
            print(f"REGREDIU {cat}: {v:.1%} (era {ref:.1%})")
            ok = False
    bom = ok and vias_ok and escala_ok and dentro_ok
    print("aceite: OK" if bom else "aceite: FALHOU")
    return 0 if bom else 1


if __name__ == "__main__":
    sys.exit(main())
