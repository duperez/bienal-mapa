"""Frame único do pavilhão, compartilhado por importador e gerador.

Origem: canto NW do hall no mapa legado (x=15pt, y=105pt) ≙ região da parede
NW do prédio. Eixo x para leste, y para sul, em METROS.

O eixo y é um warp piecewise: as ruas legadas mapeiam para posições geradas
com banda/rua uniformes (a regularização do eixo vertical), e tudo o mais
(áreas, células) interpola entre esses nós — importador e gerador usam a
MESMA função, então nada desalinha por construção.
"""

HALL_X0_PT = 15.0
HALL_Y0_PT = 105.0
M_PER_PT = 322.0 / 1295.0


def x_m(x_pt: float) -> float:
    return (x_pt - HALL_X0_PT) * M_PER_PT


def build_y_warp(ruas_y_pt: list, banda_m: float, rua_m: float):
    """ruas_y_pt: y (pt legado) do topo de cada faixa de rua, ordem norte->sul.

    Retorna (warp, ruas_y_m): warp(y_pt)->y_m e a lista de y gerados das ruas.
    """
    ruas_y_pt = sorted(ruas_y_pt)
    y0_m = (ruas_y_pt[0] - HALL_Y0_PT) * M_PER_PT - banda_m  # topo da banda norte
    knots = []
    ruas_y_m = []
    y = y0_m + banda_m
    RUA_PT = 17.0
    for y_pt in ruas_y_pt:
        knots.append((y_pt, y))
        knots.append((y_pt + RUA_PT, y + rua_m))
        ruas_y_m.append(y)
        y += rua_m + banda_m

    def warp(v_pt: float) -> float:
        if v_pt <= knots[0][0]:
            return knots[0][1] + (v_pt - knots[0][0]) * M_PER_PT
        if v_pt >= knots[-1][0]:
            return knots[-1][1] + (v_pt - knots[-1][0]) * M_PER_PT
        for (o1, n1), (o2, n2) in zip(knots, knots[1:]):
            if o1 <= v_pt <= o2:
                t = (v_pt - o1) / (o2 - o1) if o2 > o1 else 0.0
                return n1 + t * (n2 - n1)
        return v_pt

    return warp, ruas_y_m
