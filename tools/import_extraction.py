"""Importador one-shot: dados extraídos do legado -> data/structure.json.

Os dados legados são CANDIDATOS em quarentena: cada relação estrutural passa
por validação formal antes de entrar. O que falha não entra em silêncio —
vira pendência em data/import-report.md para decisão humana.

O structure.json descreve o pavilhão de forma declarativa e editável:
fileiras (norte->sul), quadras dentro de fileiras, células dentro de quadras
com lado (norte/sul/cheia) e largura em METROS. Nenhuma coordenada de tela.
"""
import json
import re
from collections import defaultdict

SRC = "legacy/data/map.json"
OUT = "data/structure.json"
REPORT = "data/import-report.md"

MIOLO_X_MAX = 1015
M_PER_PT = 322.0 / 1295.0   # lado norte do prédio (OSM) / largura do hall no mapa
GAP_QUADRA_PT = 8           # vão maior que isso separa quadras
CODE_RE = re.compile(r"^([A-K])([0-9]+)$")

warnings = []
pending = []


def warn(msg):
    warnings.append(msg)


def pend(msg):
    pending.append(msg)


def main():
    m = json.load(open(SRC))

    # ---- fileiras de rua do miolo ----
    ruas = {}
    for r in m["ruas"]:
        if r["bbox"][0] < MIOLO_X_MAX and r["name"]:
            nome = r["name"].replace("RUA ", "")
            ruas.setdefault(nome, []).append(r)
    rua_y = {n: sum(b["bbox"][1] for b in v) / len(v) for n, v in ruas.items()}
    ordem_ruas = sorted(rua_y, key=lambda n: rua_y[n])  # norte -> sul
    if ordem_ruas != ["K", "J", "H", "G", "F", "E", "D", "C", "B", "A"]:
        pend(f"Ordem inesperada de ruas: {ordem_ruas}")

    # bandas de estandes: acima da 1ª rua (norte) + entre ruas consecutivas
    RUA_H_PT = 17.0
    bandas = [("norte", None, rua_y[ordem_ruas[0]])]
    for a, b in zip(ordem_ruas, ordem_ruas[1:]):
        bandas.append((f"{a}{b}", rua_y[a] + RUA_H_PT, rua_y[b]))
    # fileira ao sul da última rua (A89, A85... encaram a RUA A por baixo)
    ultima = ordem_ruas[-1]
    bandas.append((f"{ultima}sul", rua_y[ultima] + RUA_H_PT, rua_y[ultima] + RUA_H_PT + 45))

    def banda_de(cy):
        for nome, y0, y1 in bandas:
            if (y0 is None or cy >= y0 - 3) and cy <= y1 + 3:
                if y0 is None and cy > y1:
                    continue
                return nome
        return None

    # ---- células candidatas ----
    cand = [s for s in m["stands"]
            if s["bbox"][0] < MIOLO_X_MAX
            and s["cat"] in ("expositor", "patrocinador", "entidade")]

    # V3: duplicatas
    vistos = defaultdict(int)
    for s in cand:
        vistos[s["id"]] += 1
    for cid, n in vistos.items():
        if n > 1:
            pend(f"Código {cid} aparece em {n} formas — mantida a primeira, revisar")
    dedup, usados = [], set()
    for s in cand:
        if s["id"] in usados:
            continue
        usados.add(s["id"])
        dedup.append(s)
    cand = dedup

    # agrupar por banda
    por_banda = defaultdict(list)
    sem_banda = []
    for s in cand:
        cy = (s["bbox"][1] + s["bbox"][3]) / 2
        nome = banda_de(cy)
        if nome is None:
            sem_banda.append(s["id"])
            continue
        por_banda[nome].append(s)
    if sem_banda:
        pend(f"Células fora de qualquer banda do miolo (revisar): {sorted(sem_banda)}")

    fileiras = []
    for nome, y0, y1 in bandas:
        cels = sorted(por_banda.get(nome, []), key=lambda s: s["bbox"][0])
        if not cels:
            continue
        meio = ((y0 if y0 is not None else min(c["bbox"][1] for c in cels)) + y1) / 2

        # quebra em quadras por vão
        quadras = [[cels[0]]]
        for a, b in zip(cels, cels[1:]):
            gap = b["bbox"][0] - a["bbox"][2]
            # célula meia-altura pode "voltar" em x (sub-linha): não é quadra nova
            if gap > GAP_QUADRA_PT and b["bbox"][0] > a["bbox"][0]:
                quadras.append([])
            quadras[-1].append(b)

        qs = []
        for qi, q in enumerate(quadras):
            brutas = []
            for s in q:
                h = s["bbox"][3] - s["bbox"][1]
                banda_h = (y1 - y0) if y0 is not None else h
                if h > banda_h * 0.62 or y0 is None:
                    lado = "cheia"
                else:
                    lado = "norte" if (s["bbox"][1] + s["bbox"][3]) / 2 < meio else "sul"
                brutas.append({
                    "code": s["id"],
                    "cat": s["cat"],
                    "lado": lado,
                    "largura_m": round((s["bbox"][2] - s["bbox"][0]) * M_PER_PT, 2),
                    "_x": s["bbox"][0],
                    "_x1": s["bbox"][2],
                })
            # agrupa em COLUNAS: célula cheia = coluna própria; meias que se
            # sobrepõem em x (norte+sul empilhadas) dividem a mesma coluna
            colunas = []
            for c in sorted(brutas, key=lambda c: c["_x"]):
                if c["lado"] != "cheia" and colunas:
                    ult = colunas[-1]
                    overlap = min(ult["_x1"], c["_x1"]) - max(ult["_x"], c["_x"])
                    if overlap > 0.5 * min(ult["_x1"] - ult["_x"], c["_x1"] - c["_x"]) \
                            and all(v["lado"] != c["lado"] and v["lado"] != "cheia"
                                    for v in ult["celulas"]):
                        ult["celulas"].append(c)
                        ult["largura_m"] = max(ult["largura_m"], c["largura_m"])
                        ult["_x1"] = max(ult["_x1"], c["_x1"])
                        continue
                colunas.append({"largura_m": c["largura_m"], "_x": c["_x"],
                                 "_x1": c["_x1"], "celulas": [c]})
            celulas = brutas  # para as validações V1/V5 abaixo
            # V1: prefixo do código vs fileira (banda "KJ" espera K no norte, J no sul)
            if len(nome) == 2:
                cima, baixo = nome[0], nome[1]
                for c in celulas:
                    mm = CODE_RE.match(c["code"])
                    if not mm:
                        continue
                    pref = mm.group(1)
                    esperado = {"norte": cima, "sul": baixo}.get(c["lado"])
                    if esperado and pref not in (cima, baixo):
                        pend(f"{c['code']} na banda {nome}: prefixo não pertence à banda")
                    elif esperado and pref != esperado and c["lado"] != "cheia":
                        warn(f"{c['code']} ({c['lado']} da banda {nome}): "
                             f"prefixo sugere lado {'norte' if pref == cima else 'sul'}")
            # V5: larguras anômalas
            ws = sorted(c["largura_m"] for c in celulas)
            med = ws[len(ws) // 2]
            for c in celulas:
                if c["largura_m"] < 1.0:
                    pend(f"{c['code']}: largura {c['largura_m']}m implausível (mediana {med}m)")
            offset = colunas[0]["_x"] if colunas else 0
            for col in colunas:
                col.pop("_x", None)
                col.pop("_x1", None)
                for c in col["celulas"]:
                    c.pop("_x1", None)
            qs.append({"id": f"{nome}-{qi + 1}", "offset_pt": offset, "colunas": colunas})

        # V2: sequência numérica por lado dentro da fileira
        for lado in ("norte", "sul", "cheia"):
            seq = [(c["_x"], c["code"]) for q in qs for col in q["colunas"]
                   for c in col["celulas"] if c["lado"] == lado]
            nums = [(x, int(CODE_RE.match(code).group(2)))
                    for x, code in seq if CODE_RE.match(code)]
            if len(nums) >= 3:
                nums.sort()
                vals = [n for _, n in nums]
                desc = sum(b < a for a, b in zip(vals, vals[1:]))
                asc = sum(b > a for a, b in zip(vals, vals[1:]))
                dominante_desc = desc >= asc
                for (x1, v1), (x2, v2) in zip(nums, nums[1:]):
                    ok = v2 < v1 if dominante_desc else v2 > v1
                    if not ok:
                        warn(f"Banda {nome}/{lado}: sequência quebra em {v1}->{v2} "
                             f"(dominante {'desc' if dominante_desc else 'asc'})")
        for q in qs:
            for col in q["colunas"]:
                for c in col["celulas"]:
                    c.pop("_x", None)
        fileiras.append({"banda": nome, "quadras": qs})

    # offsets viram metros relativos à borda esquerda do conteúdo — as quadras
    # ficam nas COLUNAS reais do pavilhão (alinhadas verticalmente entre
    # fileiras), e os vãos entre elas são os corredores verticais
    x0_global = min(q["offset_pt"] for f in fileiras for q in f["quadras"])
    for f in fileiras:
        for q in f["quadras"]:
            q["offset_m"] = round((q["offset_pt"] - x0_global) * M_PER_PT, 2)
            del q["offset_pt"]

    # V4: diretório vs células
    directory = m.get("directory", {})
    ids = {c["code"] for f in fileiras for q in f["quadras"]
           for col in q["colunas"] for c in col["celulas"]}
    sem_nome = sorted(i for i in ids if i not in directory and CODE_RE.match(i))
    if sem_nome:
        warn(f"Células sem nome no diretório ({len(sem_nome)}): {sem_nome[:15]}...")

    out = {
        "meta": {
            "fonte": "importado da extração legada em 2026-09-02; validado por tools/import_extraction.py",
            "escala_m_por_unidade": 1.0,
            "constantes": {"banda_m": 10.0, "rua_m": 4.2, "celula_profundidade_m": 7.4,
                            "corredor_vertical_m": 5.0, "respiro_m": 1.2},
        },
        "fileiras": fileiras,
        "directory": directory,
        "travessa": m.get("travessa", {}),
        "pendencias": pending,
    }
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)

    with open(REPORT, "w") as f:
        f.write("# Relatório de importação da extração legada\n\n")
        f.write(f"- células importadas: {len(ids)}\n")
        f.write(f"- fileiras: {len(fileiras)}\n")
        f.write(f"- nomes no diretório: {len(directory)}\n\n")
        f.write(f"## Pendências (exigem decisão) — {len(pending)}\n\n")
        for p in pending:
            f.write(f"- [ ] {p}\n")
        f.write(f"\n## Avisos (observações, não bloqueiam) — {len(warnings)}\n\n")
        for w in warnings:
            f.write(f"- {w}\n")
        f.write("\n## Fora do escopo desta importação (entram em rodadas próprias)\n\n")
        f.write("- Áreas (praças, alimentação, serviços, infra) e seus códigos IF/K/EXT\n")
        f.write("- Anexo (ruas AA–DD, autógrafos, cordel)\n")
        f.write("- Alameda dos Artistas (TI) e Travessa Literária (geometria)\n")
        f.write("- Marcadores de ponta de fileira\n")

    print(f"células: {len(ids)} | fileiras: {len(fileiras)} | "
          f"pendências: {len(pending)} | avisos: {len(warnings)}")


if __name__ == "__main__":
    main()
