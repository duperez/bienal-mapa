"""Exploração inicial do PDF oficial: agrupa desenhos por cor de preenchimento."""
import pymupdf
from collections import Counter, defaultdict

doc = pymupdf.open("reference/mapa-oficial.pdf")
page = doc[0]
print("page rect:", page.rect)

drawings = page.get_drawings()
print("total drawings:", len(drawings))

def key(color):
    if color is None:
        return None
    return tuple(round(c * 255) for c in color)

by_fill = defaultdict(list)
for d in drawings:
    by_fill[key(d["fill"])].append(d)

for fill, items in sorted(by_fill.items(), key=lambda kv: -len(kv[1]))[:20]:
    rects = [d["rect"] for d in items]
    ws = sorted(r.width for r in rects)
    hs = sorted(r.height for r in rects)
    n = len(items)
    print(f"fill {fill}: n={n} w_med={ws[n//2]:.1f} h_med={hs[n//2]:.1f} "
          f"w_range=({ws[0]:.0f},{ws[-1]:.0f}) h_range=({hs[0]:.0f},{hs[-1]:.0f})")

# formas azul-expositor: quantos itens de path são retângulos puros?
BLUE = (193, 235, 251)
blues = by_fill.get(BLUE) or by_fill.get((193, 235, 252)) or []
# procurar a cor mais próxima do azul da legenda caso arredondamento difira
if not blues:
    for fill, items in by_fill.items():
        if fill and abs(fill[0] - 193) < 6 and abs(fill[1] - 235) < 6 and abs(fill[2] - 251) < 6:
            print("azul encontrado como", fill)
            blues = items
            break
print("\nestandes azuis:", len(blues))
shapes = Counter()
for d in blues:
    ops = "".join(it[0] for it in d["items"])
    shapes[ops] += 1
print("composição dos paths azuis (re=rect, l=line, c=curve):", shapes.most_common(10))

# amostra de texto
words = page.get_text("words")
print("\ntotal words:", len(words))
print("amostra:", [w[4] for w in words[:10]])
