"""Quanto do corredor real tem uma via nomeada em cima.

O passo a passo do app só sabe dizer "siga pela RUA H" se existir uma feature
`kind: "via"` cobrindo o pedaço que a pessoa está andando. Quando não existe, o
passo sai como "siga em frente por 40 m" — o que não orienta ninguém dentro de
um corredor cercado por paredes de 3 m.

Este medidor não olha rota nenhuma: olha o corredor inteiro que o build derivou
e pergunta que fração dele tem via por cima. É a métrica honesta de cobertura,
porque não depende de quais pares de pontos eu resolvi sortear.

Uso: .venv/bin/python tools/cobertura_vias.py
"""
import sys

from shapely.geometry import LineString
from shapely.ops import unary_union

sys.path.insert(0, "tools")
import build_map as B


def corredor_e_vias():
    """Roda o pedaço do build que produz corredor e vias, sem gravar nada."""
    import pymupdf

    page = pymupdf.open(B.PDF)[0]
    box = pymupdf.Rect(*B.MAP_CLIP)
    formas, m_per_pt = B.extrair(page, box)
    labels = B.rotulos(page, box, m_per_pt)

    lx0, ly0 = ((B.LEGENDA[0] - box.x0) * m_per_pt, (B.LEGENDA[1] - box.y0) * m_per_pt)
    lx1, ly1 = ((B.LEGENDA[2] - box.x0) * m_per_pt, (B.LEGENDA[3] - box.y0) * m_per_pt)

    ocupados, setas = [], []
    tv0, tv1 = ((B.TRAVESSA[0] - box.x0) * m_per_pt, (B.TRAVESSA[1] - box.y0) * m_per_pt)
    tv2, tv3 = ((B.TRAVESSA[2] - box.x0) * m_per_pt, (B.TRAVESSA[3] - box.y0) * m_per_pt)

    for f in formas:
        ext = max(f["aneis"], key=lambda r: abs(B.ring_area(r)))
        area = abs(B.ring_area(ext))
        if area < 0.5 or all(lx0 <= x <= lx1 and ly0 <= y <= ly1 for x, y in ext):
            continue
        xs = [p[0] for p in ext]
        ys = [p[1] for p in ext]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        na_tv = tv0 <= cx <= tv2 and tv1 <= cy <= tv3
        kind, cat = B.classificar(f["cor"], ext, area, na_tv)
        if kind is None:
            continue
        if kind == "rua":
            dentro = [t["txt"] for t in labels if B.in_ring((t["x"], t["y"]), ext)]
            nome = " ".join(dentro).strip() or None
            if nome and B.RUA_RE.match(nome):
                setas.append({"nome": nome.upper(), "cx": cx, "cy": cy,
                              "eixo": "y" if max(xs) - min(xs) >= max(ys) - min(ys) else "x"})
            continue
        if kind in ("poi",) or cat == "travessa":
            continue
        ocupados.append(ext)

    ocupado, corr, caminhavel = B.circulacao(ocupados)
    vias = B.eixos(ocupado, corr, "y") + B.eixos(ocupado, corr, "x")
    return corr, caminhavel, vias, setas


def mede(corr, vias, folga=0.0):
    """Fração da área de corredor que tem via por cima."""
    faixas = [LineString(l).buffer(v["largura"] / 2 + folga, cap_style=2)
              for v in vias for l in v.get("linhas", [])]
    if not faixas:
        return 0.0, corr
    cobertura = unary_union(faixas)
    dentro = corr.intersection(cobertura)
    return dentro.area / corr.area, corr.difference(cobertura)


def main():
    corr, caminhavel, vias, setas = corredor_e_vias()
    print(f"corredor: {corr.area:,.0f} m2   vias brutas: {len(vias)}   setas: {len(setas)}")

    for folga in (0.0, 1.0, 2.0, 4.0):
        frac, fora = mede(corr, vias, folga)
        print(f"  folga {folga:4.1f} m -> cobertura {frac * 100:5.1f}%   "
              f"sobra {fora.area:7,.0f} m2")

    # onde estão os buracos: pedaços grandes de corredor sem via nenhuma
    _, fora = mede(corr, vias, 1.0)
    pedacos = sorted(getattr(fora, "geoms", [fora]), key=lambda p: -p.area)
    print("\nmaiores buracos de cobertura (corredor sem via):")
    for p in pedacos[:12]:
        if p.area < 20:
            break
        x0, y0, x1, y1 = p.bounds
        print(f"  {p.area:7,.0f} m2   {x1 - x0:6.1f} x {y1 - y0:6.1f} m   "
              f"em [{(x0 + x1) / 2:6.1f}, {(y0 + y1) / 2:6.1f}]")

    # e o que o filtro de comprimento derruba
    curtas = [v for v in vias if v["ext"] < B.EXT_ANON]
    print(f"\nvias brutas com ext < EXT_ANON ({B.EXT_ANON} m): {len(curtas)} de {len(vias)}")
    for v in sorted(curtas, key=lambda v: -v["ext"])[:10]:
        print(f"  eixo {v['eixo']}  ext {v['ext']:5.1f} m  larg {v['largura']:4.1f} m  "
              f"centro {v['centro']:6.1f}")


if __name__ == "__main__":
    main()
