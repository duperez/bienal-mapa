"""Mede a escala do desenho oficial a partir do módulo construtivo dos estandes.

Por que isto existe: a escala do mapa não pode ser deduzida do prédio. O PDF da
Bienal é um desenho de divulgação, cortado à esquerda e no rodapé, e não nomeia
o local nem desenha as paredes — casar a largura do recorte com a largura do
Distrito Anhembi (322 m) era um palpite, e estava 11% errado.

O que sobra é evidência interna. Estande de feira é montado em módulo: as
frentes são múltiplos inteiros de 1 m (3x3, 6x3, 9x6...). Então a escala certa é
aquela em que os lados medidos caem em cima de números inteiros. Rodando a
escala de 0,80 a 1,15 do palpite antigo, isso dá uma curva com mínimo único.

    python tools/calibra.py

Saída: a escala do desenho em metros, o desvio residual e o intervalo de
confiança por bootstrap. O resultado alimenta ESCALA_M_PT em tools/build_map.py.
"""
import random
import sys

import pymupdf
from shapely.geometry import Polygon

sys.path.insert(0, "tools")
from build_map import (ESCALA_M_PT, LEGENDA, MAP_CLIP, TRAVESSA, classificar,  # noqa: E402
                        extrair, ring_area)

MIN_L, MAX_L = 0.5, 40.0   # abaixo é ruído de traço, acima não é lado de estande
VARRE = (0.80, 1.15)       # faixa de busca, relativa à escala atual
PASSO = 0.0001
AMOSTRAS = 60              # repetições do bootstrap


def lados():
    """Lados dos blocos de estande do PDF, na escala atual.

    Só entram os blocos que o build classifica como estande ou área nomeada.
    Passar todos os paths preenchidos afoga o sinal: o PDF tem milhares de
    lados de logotipo, ícone e ornamento, que não obedecem módulo nenhum e
    deixam a curva plana.
    """
    page = pymupdf.open("reference/mapa-oficial.pdf")[0]
    box = pymupdf.Rect(*MAP_CLIP)
    formas, mpp = extrair(page, box)
    lx0, ly0 = (LEGENDA[0] - box.x0) * mpp, (LEGENDA[1] - box.y0) * mpp
    lx1, ly1 = (LEGENDA[2] - box.x0) * mpp, (LEGENDA[3] - box.y0) * mpp
    tv0, tv1 = (TRAVESSA[0] - box.x0) * mpp, (TRAVESSA[1] - box.y0) * mpp
    tv2, tv3 = (TRAVESSA[2] - box.x0) * mpp, (TRAVESSA[3] - box.y0) * mpp
    out = []
    for f in formas:
        anel = max(f["aneis"], key=lambda r: abs(ring_area(r)))
        p = Polygon(anel)
        if not p.is_valid:
            p = p.buffer(0)
        if p.is_empty:
            continue
        c = p.centroid
        if lx0 < c.x < lx1 and ly0 < c.y < ly1:      # a legenda não é planta
            continue
        na_tv = tv0 < c.x < tv2 and tv1 < c.y < tv3
        kind, _ = classificar(f["cor"], anel, p.area, na_tv)
        if kind not in ("estande", "area"):
            continue
        for a, b in zip(anel, anel[1:]):
            L = ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
            if MIN_L < L < MAX_L:
                out.append(L)
    return out


def desvio(am, s):
    """Distância média ao múltiplo de 1 m mais próximo, na escala s.

    Dividir pelo passo do módulo é o que torna a métrica comparável entre
    escalas: sem isso a curva premiaria s -> 0, onde tudo vira zero.
    """
    return sum(min((L * s) % 1.0, 1 - (L * s) % 1.0) for L in am) / len(am)


def melhor(am):
    lo, hi = int(VARRE[0] / PASSO), int(VARRE[1] / PASSO)
    return min(((desvio(am, i * PASSO), i * PASSO) for i in range(lo, hi)))[1]


def main():
    am = lados()
    s = melhor(am)
    print(f"lados medidos      : {len(am)}")
    print(f"escala relativa    : {s:.4f}")
    print(f"escala medida      : {ESCALA_M_PT * s:.6f} m/pt  "
          f"(constante atual {ESCALA_M_PT:.6f} x {s:.4f})")
    print(f"desvio residual    : {desvio(am, s) * 100:.1f} cm   "
          f"(aleatório seria 25,0 cm)")
    print(f"desvio em s=1      : {desvio(am, 1.0) * 100:.1f} cm")

    random.seed(7)
    bs = sorted(melhor([random.choice(am) for _ in am]) for _ in range(AMOSTRAS))
    k = max(1, AMOSTRAS // 20)
    print(f"IC 90% da escala   : {bs[k]:.4f} – {bs[-k-1]:.4f}")

    print("\ncurva (cm de desvio por escala):")
    for i in range(80, 116, 2):
        print(f"   s={i / 100:4.2f}  {ESCALA_M_PT * i / 100:.6f} m/pt  "
              f"{desvio(am, i / 100) * 100:5.1f}")


if __name__ == "__main__":
    main()
