"""Deriva o grafo de corredores das faixas de rua e grava em data/map.json (chaves
graph e streets).

Heurística do grafo:
  - agrupa faixas bege em fileiras (mesma rua) por proximidade de y
  - nós: pontas de cada faixa + centro de cada vão entre faixas consecutivas
  - arestas horizontais: entre nós consecutivos da mesma fileira
  - arestas verticais: entre vãos alinhados (|dx| <= 18pt) de fileiras adjacentes,
    só quando as fileiras se sobrepõem em x (não liga hall principal ao anexo)

streets: geometria visual das ruas (renderizada no app como via de mapa, com
preenchimento e borda) — reaproveita as mesmas faixas e cruzamentos do grafo:
  - um retângulo por faixa bege extraída (o corredor em si)
  - um retângulo-ponte por vão horizontal dentro da mesma fileira (liga faixas
    vizinhas pra rua não parecer cortada)
  - uma tira vertical por aresta de conexão entre fileiras (o cruzamento)
"""
import json

GAP_MIN, GAP_MAX = 8, 90
ALIGN_TOL = 18
ROW_TOL = 10
CROSS_W = 20  # largura das tiras verticais de cruzamento (= corredor do layout)

m = json.load(open("data/map.json"))

# ---- fileiras ----
bands = sorted(m["ruas"], key=lambda r: (r["bbox"][1] + r["bbox"][3]) / 2)
rows = []
for b in bands:
    cy = (b["bbox"][1] + b["bbox"][3]) / 2
    for row in rows:
        if abs(row["y"] - cy) <= ROW_TOL:
            row["bands"].append(b)
            row["y"] = sum((x["bbox"][1] + x["bbox"][3]) / 2 for x in row["bands"]) / len(row["bands"])
            break
    else:
        rows.append({"y": cy, "bands": [b]})

nodes, edges = [], []
node_ids = {}


def node(x, y):
    key = (round(x, 1), round(y, 1))
    if key not in node_ids:
        node_ids[key] = len(nodes)
        nodes.append([round(x, 2), round(y, 2)])
    return node_ids[key]


streets = []  # retângulos de rua: {"bbox":[...]}

for row in rows:
    row["bands"].sort(key=lambda b: b["bbox"][0])
    name = next((b["name"] for b in row["bands"] if b["name"]), "")
    row["name"] = name
    y = row["y"]
    row["y0"] = min(b["bbox"][1] for b in row["bands"])
    row["y1"] = max(b["bbox"][3] for b in row["bands"])
    # visual: no miolo a rua é UMA faixa contínua de ponta a ponta (nada de
    # segmentos que "acabam no meio"); interrupção real (> GAP_MAX) é respeitada
    xs_all = sorted((b["bbox"][0], b["bbox"][2]) for b in row["bands"])
    seg_x0 = xs_all[0][0]
    prev = xs_all[0][1]
    for x0, x1 in xs_all[1:]:
        if x0 - prev > GAP_MAX:
            streets.append({"bbox": [seg_x0, row["y0"], prev, row["y1"]]})
            seg_x0 = x0
        prev = max(prev, x1)
    streets.append({"bbox": [seg_x0, row["y0"], prev, row["y1"]]})

    xs = []                      # x dos nós desta fileira, em ordem
    crossings = []               # x onde há vão (candidato a conexão vertical)
    breaks = set()               # pares (xa, xb) sem aresta (rua interrompida)
    prev_x1 = None
    prev_band = None
    for b in row["bands"]:
        x0, _, x1, _ = b["bbox"]
        if prev_x1 is None:
            xs.append(x0)
            crossings.append(x0)          # ponta esquerda também cruza
        else:
            gap = x0 - prev_x1
            if GAP_MIN <= gap <= GAP_MAX:
                cx = (prev_x1 + x0) / 2
                xs.append(cx)
                crossings.append(cx)
            elif gap > GAP_MAX:           # interrupção real: nós nas duas pontas
                breaks.add(len(xs))       # índice do 1º nó do par sem aresta
                xs.extend([prev_x1, x0])
                crossings.extend([prev_x1, x0])
        prev_x1 = x1
        prev_band = b
    xs.append(prev_x1)
    crossings.append(prev_x1)             # ponta direita

    row["crossings"] = crossings
    row["xrange"] = (row["bands"][0]["bbox"][0], prev_x1)
    ids = [node(x, y) for x in xs]
    for i, (a, b2) in enumerate(zip(ids, ids[1:])):
        if i in breaks:
            continue
        edges.append([a, b2])

rows.sort(key=lambda r: r["y"])
main_rows = [r for r in rows if (r["xrange"][0] + r["xrange"][1]) / 2 < 1270]
annex_rows = [r for r in rows if (r["xrange"][0] + r["xrange"][1]) / 2 >= 1270]
pairs = list(zip(main_rows, main_rows[1:])) + list(zip(annex_rows, annex_rows[1:]))
for r1, r2 in pairs:
    if min(r1["xrange"][1], r2["xrange"][1]) - max(r1["xrange"][0], r2["xrange"][0]) < 40:
        continue
    if r2["y"] - r1["y"] > 120:
        continue
    for cx in r1["crossings"]:
        best, best_d = None, ALIGN_TOL
        for cx2 in r2["crossings"]:
            if abs(cx2 - cx) < best_d:
                best, best_d = cx2, abs(cx2 - cx)
        if best is not None:
            edges.append([node(cx, r1["y"]), node(best, r2["y"])])
            cxm = (cx + best) / 2
            if r2["y0"] > r1["y1"]:  # só desenha tira se as fileiras não se sobrepõem em y
                streets.append({"bbox": [cxm - CROSS_W / 2, r1["y1"], cxm + CROSS_W / 2, r2["y0"]]})

# dedup de arestas
seen = set()
uniq = []
for a, b in edges:
    k = (min(a, b), max(a, b))
    if a != b and k not in seen:
        seen.add(k)
        uniq.append([a, b])

m["graph"] = {"nodes": nodes, "edges": uniq}
m["streets"] = [{"bbox": [round(v, 2) for v in s["bbox"]]} for s in streets]
json.dump(m, open("data/map.json", "w"), ensure_ascii=False, indent=1)
print(f"fileiras: {len(rows)} | nós: {len(nodes)} | arestas: {len(uniq)} | tiras de rua: {len(streets)}")
for r in rows:
    print(f"  y={r['y']:.0f} {r['name'] or '(sem nome)':10s} faixas={len(r['bands'])} cruz={len(r['crossings'])}")
