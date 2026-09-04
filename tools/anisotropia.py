"""Testa se o desenho da Bienal está esticado num eixo.

Por que isto existe: a razão de aspecto do desenho (2,03) não bate com a do
prédio real (1,44). Ou o desenho cobre uma área que não é o prédio inteiro, ou
ele foi esticado na horizontal para caber no papel junto com a lista de
expositores — o que é comum em mapa de divulgação e destruiria qualquer
calibração isotrópica.

O teste separa os lados HORIZONTAIS dos VERTICAIS dos blocos e calibra cada
eixo pelo mesmo critério do calibra.py: estande de feira é montado em módulo de
1 m, então a escala certa é a que joga os lados em cima de inteiros. Se o
desenho for isotrópico, os dois eixos têm mínimo no mesmo lugar. Se sy/sx der
perto de 1,41, a anisotropia está provada e a razão de aspecto se explica sem
mexer no venue.

    .venv/bin/python tools/anisotropia.py

Cuidado ao ler: um grid de 1 m continua sendo grid de 1 m em s, 2s, s/2... A
varredura tem vários mínimos por alias. O que este script afirma é só a RAZÃO
entre os eixos dentro da mesma janela de busca, que é imune ao alias porque os
dois eixos são varridos igual.
"""
import sys

import pymupdf
from shapely.geometry import Polygon

sys.path.insert(0, "tools")
from build_map import (ESCALA_M_PT, LEGENDA, MAP_CLIP, TRAVESSA, classificar,  # noqa: E402
                       extrair, ring_area)

MIN_L, MAX_L = 0.5, 40.0
PASSO = 0.0002
# tolerância para chamar um lado de "horizontal": 0,05 m em 0,5 m de lado é
# menos de 6 graus. Lado inclinado não obedece módulo em eixo nenhum e sai.
RETO = 0.05


def lados_por_eixo():
    page = pymupdf.open("reference/mapa-oficial.pdf")[0]
    box = pymupdf.Rect(*MAP_CLIP)
    formas, mpp = extrair(page, box)
    lx0, ly0 = (LEGENDA[0] - box.x0) * mpp, (LEGENDA[1] - box.y0) * mpp
    lx1, ly1 = (LEGENDA[2] - box.x0) * mpp, (LEGENDA[3] - box.y0) * mpp
    tv0, tv1 = (TRAVESSA[0] - box.x0) * mpp, (TRAVESSA[1] - box.y0) * mpp
    tv2, tv3 = (TRAVESSA[2] - box.x0) * mpp, (TRAVESSA[3] - box.y0) * mpp
    hor, ver = [], []
    for f in formas:
        anel = max(f["aneis"], key=lambda r: abs(ring_area(r)))
        p = Polygon(anel)
        if not p.is_valid:
            p = p.buffer(0)
        if p.is_empty:
            continue
        c = p.centroid
        if lx0 < c.x < lx1 and ly0 < c.y < ly1:
            continue
        na_tv = tv0 < c.x < tv2 and tv1 < c.y < tv3
        if classificar(f["cor"], anel, p.area, na_tv)[0] not in ("estande", "area"):
            continue
        for a, b in zip(anel, anel[1:]):
            dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
            if dy < RETO and MIN_L < dx < MAX_L:
                hor.append(dx)
            elif dx < RETO and MIN_L < dy < MAX_L:
                ver.append(dy)
    return hor, ver


def desvio(am, s):
    return sum(min((L * s) % 1.0, 1 - (L * s) % 1.0) for L in am) / len(am)


def melhor(am, lo, hi):
    return min(((desvio(am, i * PASSO), i * PASSO)
                for i in range(int(lo / PASSO), int(hi / PASSO))))[1]


def main():
    hor, ver = lados_por_eixo()
    print(f"lados horizontais: {len(hor)}   verticais: {len(ver)}")
    lo, hi = 0.80, 1.20
    sx, sy = melhor(hor, lo, hi), melhor(ver, lo, hi)
    print(f"\njanela de busca relativa: {lo} a {hi}")
    print(f"  eixo x: s={sx:.4f}  ->  {ESCALA_M_PT * sx:.6f} m/pt   "
          f"desvio {desvio(hor, sx) * 100:.1f} cm")
    print(f"  eixo y: s={sy:.4f}  ->  {ESCALA_M_PT * sy:.6f} m/pt   "
          f"desvio {desvio(ver, sy) * 100:.1f} cm")
    print(f"  sy/sx = {sy / sx:.4f}")
    print("\n  esticado na horizontal explicaria a razão de aspecto se "
          "sy/sx ~ 1,41")
    print(f"  medido: {sy / sx:.4f}  ->  "
          f"{'ANISOTRÓPICO' if abs(sy / sx - 1) > 0.05 else 'ISOTRÓPICO'}")

    print("\ncurva por eixo (cm de desvio):")
    print("     s      x     y")
    for i in range(80, 121, 2):
        s = i / 100
        print(f"  {s:4.2f}  {desvio(hor, s) * 100:5.1f} {desvio(ver, s) * 100:5.1f}")


if __name__ == "__main__":
    main()
