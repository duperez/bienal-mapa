"""PDF oficial -> mapa.geojson do app. Transcrição, não síntese.

Cadeia: geometria literal do PDF -> classificação por cor -> código por
contenção do rótulo -> afim única para lng/lat.

O que muda em relação ao gerador antigo: a posição NUNCA vem de constante de
design. Ela vem do arquivo. Categoria, código e nome são metadados pendurados
em cima; se a classificação errar, o desenho continua no lugar certo.
"""
import json
from collections import Counter
import math
import re
import sys

import pymupdf
from shapely.geometry import LineString, Polygon
from shapely.geometry import Point as shp_point
from shapely.geometry import box as shp_box

from shapely.ops import unary_union

PDF = "reference/mapa-oficial.pdf"
VENUE = "data/venue.geojson"
STRUCT = "data/structure.json"
OUT = "web/public/data/mapa.geojson"

# Janela de LEITURA do PDF: separa a planta do cabeçalho e do rodapé.
# NÃO é a extensão do desenho. A versão anterior confundia as duas coisas: a
# borda esquerda cortava 23 pt de estandes reais, que ficavam com coordenada
# negativa e vazavam para fora do prédio no app. Folga proposital nos lados.
#
# O topo era 140 e cortava a borda de SERVIÇO inteira: cinco ACESSO SERVIÇO
# HALL (triângulos em y=132,9) e dez SAÍDA DE EMERGÊNCIA (y=130,4), com os
# rótulos em y=111,8..125. Eram 15 dos 35 acessos do desenho — quase metade —
# e justamente os da fachada oposta ao público, que é a referência que prova a
# orientação. Fica em 105: pega rótulo e triângulo, e ainda exclui os círculos
# de PORTÃO 7..10 (y≈60..100), que são portões do terreno, não do pavilhão.
MAP_CLIP = (30.0, 105.0, 1560.0, 955.0)
LEGENDA = (1068.0, 266.0, 1555.0, 485.0)   # caixa da legenda: não é planta

# Escala, em metros por ponto do PDF. Antes saía de dividir uma largura suposta
# do salão pela largura do recorte — o que amarrava a escala a um enquadramento
# arbitrário e a um palpite sobre o prédio, e estava 11% grande.
#
# Agora é MEDIDA, e independente do recorte: varrendo a escala, o desvio médio
# dos lados de estande ao múltiplo de 1 m mais próximo tem mínimo único e agudo
# aqui (13,8 cm, contra 24,8 cm na escala antiga, que é indistinguível de
# aleatório). Confirmam, sem entrar na conta: o lado mais frequente vira 6,01 m
# (frente padrão de estande) e os cinco Acessos Hall ficam a 36,2 m entre si
# (vão estrutural). Reproduzir com: python tools/calibra.py
ESCALA_M_PT = 0.194875

# cores da LEGENDA do próprio PDF -> categoria. Nada inventado.
PALETA = {
    (187, 230, 251): ("estande", "expositor"),
    (237, 33, 36): ("area", "cultural"),      # espaços nomeados, não estandes
    (250, 238, 19): ("estande", "patrocinador"),
    (179, 127, 184): ("estande", "entidade"),
    (192, 226, 202): ("area", "infra"),
    (250, 163, 26): ("area", "alimentacao"),
}
# tons de vermelho/cinza que o PDF usa fora da legenda
# faces "3D" (extrusão) usam tons mais escuros da mesma cor: são sombra de
# desenho, não área ocupável. Só o topo do bloco vira feature.
ALIAS = {(235, 32, 40): (237, 33, 36), (238, 163, 26): (250, 163, 26)}
CINZA = ((198, 199, 200), (128, 129, 129), (35, 31, 32))  # estrutura/halls
RUA = (198, 177, 152)          # faixa/seta com o nome da rua
# triângulos de acesso; a cor vem da LEGENDA do PDF e diz para quem é a porta
POI = {(9, 146, 71): "entrada",            # acesso aos halls
       (97, 186, 87): "entrada",           # público com ingresso
       (205, 75, 147): "entrada-bilheteria",  # público sem ingresso
       (225, 114, 38): "entrada-expositor",
       (235, 44, 41): "saida",
       (237, 33, 36): "saida",
       (55, 185, 235): "escolas"}
TRAVESSA = (795.0, 240.0, 905.0, 360.0)   # bbox da Travessa Literária no PDF
CODE_RE = re.compile(r"[A-Z]{1,3}\d{1,3}[A-Z]?")
RUA_RE = re.compile(r"RUA\s+[A-Z]{1,2}", re.I)


def rgb(c):
    return tuple(int(round(v * 255)) for v in c)


def snap(c, tol=18):
    c = ALIAS.get(c, c)
    for k in PALETA:
        if all(abs(a - b) <= tol for a, b in zip(c, k)):
            return k
    return None


def ring_area(r):
    s = 0.0
    for i in range(len(r)):
        x0, y0 = r[i]
        x1, y1 = r[(i + 1) % len(r)]
        s += x0 * y1 - x1 * y0
    return s / 2


def in_ring(pt, ring):
    x, y = pt
    inside = False
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i - 1) % n]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside


def title_pt(s):
    if not s:
        return None
    minus = {"de", "da", "do", "das", "dos", "e", "em", "a", "o"}
    out = []
    for i, w in enumerate(s.lower().split()):
        out.append(w if i and w in minus else w.capitalize())
    return " ".join(out)


# ---------------------------------------------------------------- geometria
def extrair(page, box):
    """Cada path preenchido do PDF -> anéis em METROS. Sem heurística."""
    m_per_pt = ESCALA_M_PT

    def to_m(x, y):
        return (round((x - box.x0) * m_per_pt, 3), round((y - box.y0) * m_per_pt, 3))

    formas = []
    clip_lv = []
    for d in page.get_drawings(extended=True):
        lv = d.get("level", 0)
        while clip_lv and clip_lv[-1][0] >= lv:
            clip_lv.pop()
        if d["type"] == "clip":
            clip_lv.append((lv, d["scissor"]))
            continue
        if d["type"] == "group" or d.get("fill") is None:
            continue
        if not d["rect"].intersects(box):
            continue
        if clip_lv and not clip_lv[-1][1].intersects(d["rect"]):
            continue

        aneis, cur = [], []
        for it in d["items"]:
            if it[0] == "re":
                r = it[1]
                pts = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
                if len(it) > 2 and it[2] < 0:
                    pts.reverse()
                if cur:
                    aneis.append(cur)
                    cur = []
                aneis.append([to_m(*p) for p in pts])
            elif it[0] == "qu":
                q = it[1]
                if cur:
                    aneis.append(cur)
                    cur = []
                aneis.append([to_m(p.x, p.y) for p in (q.ul, q.ur, q.lr, q.ll)])
            elif it[0] == "l":
                a, b = to_m(it[1].x, it[1].y), to_m(it[2].x, it[2].y)
                if not cur:
                    cur = [a]
                elif cur[-1] != a:
                    aneis.append(cur)
                    cur = [a]
                cur.append(b)
            elif it[0] == "c":
                p0, c1, c2, p3 = it[1:5]
                a = to_m(p0.x, p0.y)
                if not cur:
                    cur = [a]
                elif cur[-1] != a:
                    aneis.append(cur)
                    cur = [a]
                for i in range(1, 7):
                    t, u = i / 6, 1 - i / 6
                    cur.append(to_m(
                        u**3 * p0.x + 3*u*u*t * c1.x + 3*u*t*t * c2.x + t**3 * p3.x,
                        u**3 * p0.y + 3*u*u*t * c1.y + 3*u*t*t * c2.y + t**3 * p3.y))
        if cur:
            aneis.append(cur)
        aneis = [a for a in aneis if len(a) >= 3 and abs(ring_area(a)) > 0.4]
        if not aneis:
            continue
        formas.append({"cor": rgb(d["fill"]), "aneis": aneis,
                       "seq": d.get("seqno", 0)})
    return desextrudar(formas), m_per_pt


def bbox(anel):
    xs = [p[0] for p in anel]
    ys = [p[1] for p in anel]
    return min(xs), min(ys), max(xs), max(ys)


def desextrudar(formas):
    """Blocos "3D" do PDF: a área ocupada é a BASE, não a face de topo.

    Patrocinadores e atividades culturais são desenhados como prismas: face de
    topo na cor da legenda, mais uma face lateral direita e uma inferior em
    outro tom. A face de topo fica deslocada ~1,4 m para cima e para a esquerda
    da posição real — é isso que jogava esses blocos para fora da fileira.

    Reconhece o prisma pelas DUAS faces auxiliares (embaixo e à direita, ambas
    com a mesma profundidade) e translada o topo para cima da base. Exigir as
    duas evita casar com vizinhança acidental de retângulo comum.
    """
    caixas = [bbox(f["aneis"][0]) for f in formas]
    def achar(x0, y0, x1, y1, tol=0.25):
        for i, c in enumerate(caixas):
            if (abs(c[0] - x0) < tol and abs(c[1] - y0) < tol
                    and abs(c[2] - x1) < tol and abs(c[3] - y1) < tol):
                return i
        return None

    faces = set()
    for k, (f, (x0, y0, x1, y1)) in enumerate(zip(formas, caixas)):
        achou = None
        for j, (gx0, gy0, gx1, gy1) in enumerate(caixas):
            if abs(gy0 - y1) > 0.25 or abs(gx0 - x0) > 0.25:
                continue
            dx, dy = gx1 - x1, gy1 - y1
            # profundidade da extrusão: positiva, pequena e igual nos dois eixos
            if not (0.5 < dx < 2.5 and 0.5 < dy < 2.5 and abs(dx - dy) < 0.4):
                continue
            lado = achar(x1, y0, x1 + dx, y1 + dy)   # face lateral direita
            if lado is not None:
                achou = (dx, dy, j, lado)
                break
        if achou:
            dx, dy, j, lado = achou
            faces.update((j, lado))
            formas[k]["extrudado"] = True
            f["aneis"] = [[(round(x + dx, 3), round(y + dy, 3)) for x, y in a]
                          for a in f["aneis"]]
    # as faces laterais são desenho do prisma, não espaço: saem da lista para
    # não virarem "estande" de 10 m2 nem serem cobradas pelo teste de aceite
    return [f for i, f in enumerate(formas) if i not in faces]


def rotulos(page, box, m_per_pt, por_linha=False):
    """Rótulos do PDF em metros.

    Por SPAN (padrão) para achar códigos de estande, que vêm soltos. Por LINHA
    (`por_linha`) para nomes: a linha é a unidade que o próprio PDF declara, e
    reconstruir o nome por proximidade de spans é o que produzia frankensteins
    como "Saída de Emergência Acesso Serviço Hall 03" — na borda de serviço os
    rótulos de acessos vizinhos ficam na mesma altura, e qualquer varredura
    lateral pega o do vizinho.
    """
    out = []
    for blk in page.get_text("dict", clip=box)["blocks"]:
        for line in blk.get("lines", []):
            if por_linha:
                t = " ".join(sp["text"] for sp in line["spans"]).strip()
                if not t:
                    continue
                bb = line["bbox"]
                out.append({
                    "txt": t,
                    "x": round(((bb[0] + bb[2]) / 2 - box.x0) * m_per_pt, 3),
                    "y": round(((bb[1] + bb[3]) / 2 - box.y0) * m_per_pt, 3),
                    "size": max(sp["size"] for sp in line["spans"]) * m_per_pt,
                })
                continue
            for sp in line["spans"]:
                t = sp["text"].strip()
                if not t:
                    continue
                bb = sp["bbox"]
                out.append({
                    "txt": t,
                    "x": round(((bb[0] + bb[2]) / 2 - box.x0) * m_per_pt, 3),
                    "y": round(((bb[1] + bb[3]) / 2 - box.y0) * m_per_pt, 3),
                    "size": sp["size"] * m_per_pt,
                })
    return out


# ------------------------------------------------------------ georreferência
def georef():
    """Afim única metros->lng/lat, ancorada no polígono real do prédio (OSM)."""
    ring = json.load(open(VENUE))["features"][0]["geometry"]["coordinates"][0]
    lat0 = ring[0][1]
    mlat, mlon = 111320.0, 111320.0 * math.cos(math.radians(lat0))
    dx = (ring[1][0] - ring[0][0]) * mlon
    dy = (ring[1][1] - ring[0][1]) * mlat
    n = math.hypot(dx, dy)
    ux, uy = (dx / n, dy / n), (dy / n, -dx / n)  # leste, sul do prédio

    def frame(p):
        mx = (p[0] - ring[0][0]) * mlon
        my = (p[1] - ring[0][1]) * mlat
        return (mx * ux[0] + my * ux[1], mx * uy[0] + my * uy[1])

    west = min(x for x, y in map(frame, ring) if abs(y) < 5)
    nw = [ring[0][0] + west * ux[0] / mlon, ring[0][1] + west * ux[1] / mlat]

    def to_lnglat(x, y):
        mx = x * ux[0] + y * uy[0]
        my = x * ux[1] + y * uy[1]
        return [round(nw[0] + mx / mlon, 7), round(nw[1] + my / mlat, 7)]

    return to_lnglat


def ancora(formas, box, m_per_pt):
    """Caixa do desenho em metros: (x0, y0, x1, y1).

    A janela de leitura tem folga proposital, e o desenho oficial ainda sai da
    página à esquerda (blocos de serviço aparecem cortados na borda). Logo nem
    o canto da janela nem a borda do papel servem de referência: sem isto, o
    que está antes da janela vira coordenada negativa e aparece do lado de fora
    da parede no app.

    A regra é: o bloco desenhado mais a noroeste encosta no canto noroeste do
    prédio. Continua sendo uma escolha — a posição real do desenho dentro do
    pavilhão é o defeito nº 4 do README — mas é declarada em um lugar só, e o
    teste de aceite cobra a consequência (nada desenhado fora do prédio).
    """
    lx0, ly0 = (LEGENDA[0] - box.x0) * m_per_pt, (LEGENDA[1] - box.y0) * m_per_pt
    lx1, ly1 = (LEGENDA[2] - box.x0) * m_per_pt, (LEGENDA[3] - box.y0) * m_per_pt
    tv0, tv1 = (TRAVESSA[0] - box.x0) * m_per_pt, (TRAVESSA[1] - box.y0) * m_per_pt
    tv2, tv3 = (TRAVESSA[2] - box.x0) * m_per_pt, (TRAVESSA[3] - box.y0) * m_per_pt
    ox, oy, fx, fy = 1e9, 1e9, -1e9, -1e9
    for f in formas:
        ext = max(f["aneis"], key=lambda r: abs(ring_area(r)))
        area = abs(ring_area(ext))
        if area < 0.5:
            continue
        xs, ys = [p[0] for p in ext], [p[1] for p in ext]
        if all(lx0 <= x <= lx1 and ly0 <= y <= ly1 for x, y in ext):
            continue                                   # legenda não é planta
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        na_tv = tv0 <= cx <= tv2 and tv1 <= cy <= tv3
        if classificar(f["cor"], ext, area, na_tv)[0] is None:
            continue
        ox, oy = min(ox, min(xs)), min(oy, min(ys))
        fx, fy = max(fx, max(xs)), max(fy, max(ys))
    return ox, oy, fx, fy


def assentamento(formas, box, m_per_pt):
    """Como o desenho assenta dentro do prédio: ida e volta, em metros.

    ROTAÇÃO DE 180°. O desenho oficial entra de cabeça para baixo, e três
    rótulos independentes provam isso:

    1. a borda de BAIXO do PDF é ENTRADA PÚBLICO; a de cima é ACESSO SERVIÇO
       HALL 01..05 com PORTÃO 7/8/9, que a planta oficial do Anhembi põe do
       lado da Marginal Tietê. A marquise do público é a face y=0 deste
       referencial (way OSM 1298216404, 258,7 m de frente).
    2. ACESSO HALL 01 está à DIREITA no PDF; a planta técnica o põe no Expo 01,
       colado na Alameda de Conexão, que é a face oeste (x=0, way 1298216400).
    3. as três saídas da borda esquerda do PDF batem com o Expo 05, único
       pavilhão com "Lateral 01/02" na tabela oficial de sanitários.

    Os três apontam para o MESMO giro, e nos dois eixos ao mesmo tempo — que é
    exatamente o que separa rotação de espelhamento. Espelhar dá distância
    menor às marquises (10,2 m contra 26,0 m), mas ninguém imprime mapa
    espelhado: a métrica de distância não sabe distinguir reflexão de giro, e
    quem decide isso é o rótulo, não o ajuste.

    Continua sendo o defeito 4 do README a POSIÇÃO exata do desenho dentro do
    pavilhão; o que esta função resolve é a orientação.
    """
    ox, oy, fx, fy = ancora(formas, box, m_per_pt)
    largura, fundo = fx - ox, fy - oy

    def para_predio(x, y):
        return (largura - (x - ox), fundo - (y - oy))

    def para_desenho(x, y):
        return (largura - x + ox, fundo - y + oy)

    return para_predio, para_desenho


def subdividir(ext, codes):
    """Bloco com N códigos -> N células, cortadas nos pontos médios REAIS
    entre rótulos vizinhos.

    O PDF oficial frequentemente não desenha a divisa entre estandes vizinhos —
    só imprime os códigos dentro do mesmo retângulo. A divisão é derivada da
    posição dos rótulos, não de um passo de grid: o erro fica CONTIDO dentro do
    bloco real em vez de propagar pela fileira inteira.
    """
    xs = [p[0] for p in ext]
    ys = [p[1] for p in ext]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if len(codes) == 1:
        return [(ext, codes[0])]

    # linhas de rótulo: agrupa por y quando o bloco tem 2 fileiras costa a costa
    codes = sorted(codes, key=lambda c: (c["y"], c["x"]))
    tol = (y1 - y0) / 3
    linhas = []
    for c in codes:
        if linhas and abs(c["y"] - linhas[-1][0]) <= tol:
            linhas[-1][1].append(c)
        else:
            linhas.append((c["y"], [c]))
    linhas = [(y, sorted(g, key=lambda c: c["x"])) for y, g in linhas]

    cortes_y = [y0] + [(linhas[i][0] + linhas[i + 1][0]) / 2
                       for i in range(len(linhas) - 1)] + [y1]
    saida = []
    for i, (_, grupo) in enumerate(linhas):
        ya, yb = cortes_y[i], cortes_y[i + 1]
        cortes_x = [x0] + [(grupo[j]["x"] + grupo[j + 1]["x"]) / 2
                           for j in range(len(grupo) - 1)] + [x1]
        for j, c in enumerate(grupo):
            xa, xb = cortes_x[j], cortes_x[j + 1]
            saida.append(([(xa, ya), (xb, ya), (xb, yb), (xa, yb)], c))
    return saida


def classificar(cor, ext, area, na_travessa):
    """Cor + forma -> (kind, cat). Regra ÚNICA, usada pelo build e pelo teste.

    Duplicar essa decisão nos dois lados faria o teste validar a si mesmo e
    divergir em silêncio.
    """
    if cor == RUA:
        return "rua", None
    if cor in POI and area < 4 and len(ext) <= 4:
        return "poi", POI[cor]
    if cor == (255, 255, 255) and area < 3.0 and na_travessa:
        return "estande", "travessa"
    alvo = snap(cor)
    if alvo is not None and area >= 1.0:
        kind, cat = PALETA[alvo]
        # tarja fina na ponta da fileira: marcador colorido de desenho (mesma
        # espessura da extrusão, altura da fileira inteira), não espaço ocupável
        x0, y0, x1, y1 = bbox(ext)
        lo, hi = sorted((x1 - x0, y1 - y0))
        if lo < 1.8 and hi > 2.5 * lo:
            return None, None
        # área de serviço/alimentação com 1 m2 é fragmento de ícone, não espaço
        if kind == "area" and area < 5.0:
            return None, None
        return kind, cat
    if cor in CINZA and area >= 1.0:
        return "piso", None      # nome de camada que o app já desenha
    return None, None


# ---------------------------------------------------------------- circulação
# O PDF não desenha as ruas: desenha SETAS com o nome delas. A rua de verdade
# é o espaço que sobra entre os blocos. Então a geometria continua saindo do
# PDF (por complemento), e a seta vira o que ela sempre foi: o rótulo.
FECHO = 12.0        # m: fecha vão até 24 m -> corredor entra, vazio externo não
LARG_MIN = 2.0      # m: abaixo disso é fresta de montagem, não passagem
LARG_MAX = 12.0     # m: acima disso é salão/praça aberta, não rua
LARG_ABERTA = 20.0  # m: via de borda, sem quarteirão do outro lado, vai até aqui
AMOSTRA = 1.0       # m: passo de amostragem ao longo da via
TOL_CENTRO = 1.5    # m: quanto o centro do corredor pode oscilar e ainda ser a mesma via
HIATO = 14.0        # m: hiato tolerado na trilha (cruzamento com via transversal)
AVENTAL = 6.0       # m: faixa caminhável rente a qualquer bloco
EXT_MIN = 12.0      # m: piso absoluto de comprimento de corredor
EXT_ANON = 20.0     # m: sem seta que a nomeie, a via precisa ser longa para entrar


def circulacao(ocupados):
    """Espaço livre entre os blocos, sem o vazio de fora do salão.

    Fecho morfológico (dilata e volta): o vão entre fileiras some, mas a área
    aberta ao sul do pavilhão continua fora. Depois uma abertura descarta o que
    é estreito demais para ser passagem.
    """
    ocupado = unary_union([Polygon(r).buffer(0) for r in ocupados])
    fecho = ocupado.buffer(FECHO, join_style=2).buffer(-FECHO, join_style=2)
    meia = LARG_MIN / 2

    def abre(g):
        return g.difference(ocupado).buffer(-meia, join_style=2).buffer(meia, join_style=2)

    # corredor: só o vão entre quarteirões. É daqui que as ruas são derivadas.
    corr = abre(fecho)
    # caminhável: o corredor mais a faixa rente aos blocos. Quem está na borda
    # do salão só tem acesso pela área aberta, que o fecho descarta — mas essa
    # faixa não pode virar rua, senão o contorno de cada bloco vira avenida.
    x0, y0, x1, y1 = ocupado.bounds
    avental = ocupado.buffer(AVENTAL, join_style=2).intersection(shp_box(x0, y0, x1, y1))
    return ocupado, corr, abre(fecho.union(avental))


def _corte(eixo, a, b0, b1):
    return LineString([(a, b0), (a, b1)] if eixo == "x" else [(b0, a), (b1, a)])


def _maior(geom):
    partes = [p for p in getattr(geom, "geoms", [geom]) if p.length > 0]
    return max(partes, key=lambda p: p.length) if partes else None


def _trecho(geom, alvo):
    """Do recorte, o pedaço que passa pelo ponto alvo (o resto é outra rua)."""
    for p in getattr(geom, "geoms", [geom]):
        if p.length > 0 and p.distance(shp_point(*alvo)) < 0.6:
            return p
    return None


def semente(seta, corr, ocupado):
    """Constrói a via a partir da seta, quando a varredura não a achou.

    O eixo é o da própria seta — o PDF a desenhou deitada em cima da rua. A
    largura é medida ao lado da seta, porque o centro dela costuma cair num
    cruzamento, onde o vão é o cruzamento inteiro e não a rua.
    """
    x0, y0, x1, y1 = ocupado.bounds
    eixo, cx, cy = seta["eixo"], seta["cx"], seta["cy"]
    centro = cy if eixo == "y" else cx
    ao_longo = cx if eixo == "y" else cy

    larguras = []
    for d in (-12.0, -10.0, -8.0, -6.0, -5.0, -4.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0):
        a = ao_longo + d
        perp = _corte("x" if eixo == "y" else "y", a,
                      *((y0, y1) if eixo == "y" else (x0, x1)))
        alvo = (a, centro) if eixo == "y" else (centro, a)
        vao = _trecho(perp.intersection(corr), alvo)
        if vao is not None and LARG_MIN <= vao.length <= LARG_ABERTA:
            larguras.append(vao.length)
    if not larguras:
        return None

    linha = _corte(eixo, centro, *((x0, x1) if eixo == "y" else (y0, y1)))
    trecho = _trecho(linha.intersection(corr), (cx, cy))
    if trecho is None or trecho.length < EXT_MIN:
        return None
    larg = sorted(larguras)[len(larguras) // 2]
    return {"eixo": eixo, "centro": centro,
            # vão maior que uma rua = a via corre na borda e o outro lado é
            # salão aberto; o eixo continua sendo o da seta, que é o dado real
            "largura": round(min(larg, LARG_MAX), 1), "aberta": larg > LARG_MAX,
            "ext": trecho.length, "linha": list(trecho.coords),
            "nome": seta["nome"], "derivado": False}


def eixos(ocupado, corr, eixo):
    """Corredores retos, achados pela largura LOCAL do vão.

    Em cada amostra perpendicular ao eixo, os trechos livres viram candidatos:
    um trecho entre 2 e 12 m é vão de corredor; abaixo é fresta de montagem,
    acima é praça (que já está na circulação e não precisa virar rua).
    Candidatos com o mesmo centro ao longo do eixo formam uma via.

    Medir o vão local, e não a fatia inteira do salão, é o que faz a RUA A e as
    ruas curtas do anexo aparecerem sem fundir as ruas vizinhas do miolo.
    """
    x0, y0, x1, y1 = ocupado.bounds
    a0, a1 = (x0, x1) if eixo == "y" else (y0, y1)   # onde amostrar
    b0, b1 = (y0, y1) if eixo == "y" else (x0, x1)   # onde medir o vão

    achados = []
    a = a0
    while a <= a1:
        corte = _corte("x" if eixo == "y" else "y", a, b0, b1)
        for p in getattr(corte.intersection(corr), "geoms", [corte.intersection(corr)]):
            if LARG_MIN <= p.length <= LARG_MAX:
                (px0, py0, px1, py1) = p.bounds
                centro = (py0 + py1) / 2 if eixo == "y" else (px0 + px1) / 2
                achados.append((a, centro, p.length))
        a += AMOSTRA

    # rastreia cada corredor: mesma via = amostras seguidas com centro estável.
    # Agrupar só pelo centro fundiria o anexo com o miolo, que ficam no mesmo
    # y mas em pontas opostas do salão.
    trilhas = []
    for a, centro, larg in achados:
        for t in trilhas:
            if a - t[-1][0] <= HIATO and abs(centro - t[-1][1]) <= TOL_CENTRO:
                t.append((a, centro, larg))
                break
        else:
            trilhas.append([(a, centro, larg)])

    vias = []
    for t in trilhas:
        if t[-1][0] - t[0][0] < EXT_MIN:
            continue
        centro = sorted(s[1] for s in t)[len(t) // 2]
        larg = sorted(s[2] for s in t)[len(t) // 2]
        corte = _corte(eixo, centro, t[0][0], t[-1][0])
        maior = _maior(corte.intersection(corr))
        if maior is None or maior.length < EXT_MIN:
            continue
        vias.append({"eixo": eixo, "centro": centro, "largura": round(larg, 1),
                     "ext": maior.length, "linha": list(maior.coords)})
    return vias


def main():
    page = pymupdf.open(PDF)[0]
    box = pymupdf.Rect(*MAP_CLIP)
    formas, m_per_pt = extrair(page, box)
    labels = rotulos(page, box, m_per_pt)
    linhas_txt = rotulos(page, box, m_per_pt, por_linha=True)
    codigos = [l for l in labels if CODE_RE.fullmatch(l["txt"])]
    # o corte de tamanho separa rótulo de planta de miudeza de desenho. Estava
    # em 1,0 m e derrubava a faixa de 0,97 m inteira — que não é miudeza: são
    # AUDITÓRIO, ESPAÇO EDUCAÇÃO, ESPAÇO BEM-ESTAR, PAPO DE MERCADO, PODCAST,
    # LOCKERS e os dez rótulos da borda de serviço. Abaixo de 0,9 m só há a
    # numeração da Travessa (0,55 m) e a tradução em inglês (0,78 m), que
    # duplicaria todo nome. O degrau é limpo: o corte fica entre os dois.
    nomes = [l for l in linhas_txt if not CODE_RE.fullmatch(l["txt"]) and l["size"] > 0.9]

    # a caixa da LEGENDA é desenho de legenda, não planta: fora.
    lx0, ly0 = ((LEGENDA[0] - box.x0) * m_per_pt, (LEGENDA[1] - box.y0) * m_per_pt)
    lx1, ly1 = ((LEGENDA[2] - box.x0) * m_per_pt, (LEGENDA[3] - box.y0) * m_per_pt)

    def na_legenda(r):
        return all(lx0 <= x <= lx1 and ly0 <= y <= ly1 for x, y in r)

    directory = json.load(open(STRUCT)).get("directory", {})

    para_predio, _ = assentamento(formas, box, m_per_pt)
    base = georef()

    def to_lnglat(x, y):
        return base(*para_predio(x, y))

    def poly(ring, props):
        return {"type": "Feature", "properties": props,
                "geometry": {"type": "Polygon", "coordinates": [
                    [to_lnglat(x, y) for x, y in ring] + [to_lnglat(*ring[0])]]}}

    feats = []
    usados = set()
    ruas = []
    ocupados = []
    setas = []
    tv0, tv1 = ((TRAVESSA[0] - box.x0) * m_per_pt, (TRAVESSA[1] - box.y0) * m_per_pt)
    tv2, tv3 = ((TRAVESSA[2] - box.x0) * m_per_pt, (TRAVESSA[3] - box.y0) * m_per_pt)
    tl_cells = []

    for f in formas:
        ext = max(f["aneis"], key=lambda r: abs(ring_area(r)))
        area = abs(ring_area(ext))
        if area < 0.5 or na_legenda(ext):
            continue
        xs = [p[0] for p in ext]
        ys = [p[1] for p in ext]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

        na_tv = tv0 <= cx <= tv2 and tv1 <= cy <= tv3
        kind, cat = classificar(f["cor"], ext, area, na_tv)
        if kind is None:
            continue

        # ---- faixa de rua: o nome corre ao longo dela, como no PDF ----
        if kind == "rua":
            dentro = [t["txt"] for t in labels if in_ring((t["x"], t["y"]), ext)]
            nome = " ".join(dentro).strip() or None
            if nome and not RUA_RE.match(nome):
                nome = None
            feats.append(poly(ext, {"kind": "rua", "cat": None, "code": None,
                                    "name": nome, "area_m2": round(area, 1)}))
            if nome:
                ys = [p[1] for p in ext]
                setas.append({"nome": nome.upper(), "cx": cx, "cy": cy,
                              # a seta aponta ao longo da rua: o lado maior dela
                              # diz qual eixo ela nomeia
                              "eixo": "y" if max(xs) - min(xs) >= max(ys) - min(ys) else "x"})
            continue

        # ---- POI: triângulo de entrada/saída, categoria pela cor da legenda ----
        if kind == "poi":
            perto = sorted(
                (t for t in nomes if re.match(r"(ENTRADA|SA[ÍI]DA|ACESSO)", t["txt"], re.I)),
                key=lambda t: (t["x"] - cx) ** 2 + (t["y"] - cy) ** 2)
            nome = None
            # o rótulo tem que estar colado no triângulo; senão é de OUTRO
            # acesso e a "melhor aproximação" viraria nome errado no app.
            # 8 m sai de medir os 35 triângulos contra o rótulo mais próximo: os
            # que têm dono ficam entre 2,03 e 3,93 m, o primeiro órfão está a
            # 14,59 m. O vão é limpo, e o corte fica no meio dele.
            if perto and math.dist((perto[0]["x"], perto[0]["y"]), (cx, cy)) < 8.0:
                nome = perto[0]["txt"]
            feats.append({"type": "Feature", "properties": {
                "kind": "poi", "cat": cat, "name": title_pt(nome)},
                "geometry": {"type": "Point", "coordinates": to_lnglat(cx, cy)}})
            continue

        # ---- Travessa Literária: cabines desenhadas em branco com contorno ----
        if cat == "travessa":
            tl_cells.append((cy, cx, ext))
            continue
        # o código é o rótulo QUE ESTÁ DENTRO da forma. Sem inferir sequência,
        # sem sortear por proximidade de fileira.
        dentro = [c for c in codigos
                  if id(c) not in usados and in_ring((c["x"], c["y"]), ext)]
        for c in dentro:
            usados.add(id(c))

        if kind == "estande" and dentro:
            ocupados.append(ext)
            for ring, c in subdividir(ext, dentro):
                a = abs(ring_area(ring))
                props = {"kind": "estande", "cat": cat, "code": c["txt"],
                         "name": title_pt(directory.get(c["txt"])),
                         "area_m2": round(a, 1)}
                if a < 6:
                    props["mini"] = True
                feats.append(poly(ring, props))
            continue

        texto = [t for t in nomes if in_ring((t["x"], t["y"]), ext)]
        texto.sort(key=lambda t: (t["y"], t["x"]))
        nome = title_pt(" ".join(t["txt"] for t in texto)) if texto else None
        # as praças de alimentação não trazem texto dentro do bloco: o nome vem
        # da própria legenda do PDF (categoria), sinalizado como derivado
        derivado = False
        if nome is None and cat == "alimentacao":
            nome, derivado = "Praça de Alimentação", True
        rings = [ext] + [r for r in f["aneis"]
                         if r is not ext and area > abs(ring_area(r)) > 1.0]
        coords = [[to_lnglat(x, y) for x, y in r] + [to_lnglat(*r[0])] for r in rings]
        props = {"kind": kind, "cat": cat,
                 "code": dentro[0]["txt"] if dentro else None,
                 "name": nome, "area_m2": round(area, 1),
                 "peso": round(area, 1)}
        if derivado:
            props["nome_derivado"] = True
        ocupados.append(ext)
        feats.append({"type": "Feature", "geometry": {
            "type": "Polygon", "coordinates": coords}, "properties": props})

    # ---- Travessa Literária: geometria é do PDF; a NUMERAÇÃO é derivada ----
    # O PDF não imprime TL01..TL48 nas cabines. A ordem de leitura é uma
    # suposição, marcada como tal — se estiver errada, troca o rótulo, não o
    # desenho. É a diferença entre metadado errado e mapa errado.
    travessa = json.load(open(STRUCT)).get("travessa", {})
    tl_cells.sort(key=lambda t: (round(t[0] / 2), t[1]))
    for i, (_, _, ring) in enumerate(tl_cells, start=1):
        nome = travessa.get(str(i))
        feats.append(poly(ring, {
            "kind": "estande", "cat": "travessa", "code": f"TL{i:02d}",
            "name": title_pt(nome), "mini": True, "numeracao_derivada": True,
            "area_m2": round(abs(ring_area(ring)), 1)}))

    feats.extend(ruas)

    # ---- circulação e vias: geometria por complemento, nome vindo da seta ----
    ocupado, corr, caminhavel = circulacao(ocupados + [t[2] for t in tl_cells])
    for parte in getattr(caminhavel, "geoms", [caminhavel]):
        aneis = [list(parte.exterior.coords)] + [list(i.coords) for i in parte.interiors]
        feats.append({"type": "Feature", "properties": {
            "kind": "circulacao", "area_m2": round(parte.area, 1)},
            "geometry": {"type": "Polygon", "coordinates": [
                [to_lnglat(x, y) for x, y in a] for a in aneis]}})

    longit = eixos(ocupado, corr, "y")
    transv = eixos(ocupado, corr, "x")
    for v in longit + transv:
        # a seta tem que cair DENTRO da via, não só no mesmo eixo: a RUA C do
        # miolo e o corredor do anexo compartilham o y e são ruas diferentes
        faixa = LineString(v["linha"]).buffer(v["largura"] / 2 + 1.0, cap_style=2)
        cand = [s["nome"] for s in setas if s["eixo"] == v["eixo"]
                and faixa.contains(shp_point(s["cx"], s["cy"]))]
        v["nome"] = Counter(cand).most_common(1)[0][0] if cand else None
        v["derivado"] = not cand
    # seta que não caiu em nenhuma via vira semente: o PDF afirma que a rua
    # existe, então ela entra pelo corredor que passa por baixo da seta
    achadas = {v["nome"] for v in longit + transv if v["nome"]}
    for s in setas:
        if s["nome"] in achadas:
            continue
        v = semente(s, corr, ocupado)
        if v:
            achadas.add(s["nome"])
            (longit if v["eixo"] == "y" else transv).append(v)

    # seta nomeada é prova de que a rua existe: entra mesmo curta. Sem nome,
    # só entra se for longa — assim recorte de canto não vira rua inventada.
    longit = [v for v in longit if v["nome"] or v["ext"] >= EXT_ANON]
    transv = [v for v in transv if v["nome"] or v["ext"] >= EXT_ANON]
    for grupo, rotulo in ((transv, "Transversal"), (longit, "Alameda")):
        anon = sorted([v for v in grupo if not v["nome"]], key=lambda v: v["centro"])
        for i, v in enumerate(anon, start=1):
            v["nome"] = f"{rotulo} {i:02d}"

    # trechos da mesma rua separados por um cruzamento largo continuam a mesma rua
    juntas = {}
    for v in longit + transv:
        juntas.setdefault((v["nome"], v["eixo"]), []).append(v)
    for (nome, eixo), partes in juntas.items():
        props = {"kind": "via", "name": nome, "eixo": eixo,
                 "largura_m": round(sum(p["largura"] for p in partes) / len(partes), 1),
                 "extensao_m": round(sum(LineString(p["linha"]).length for p in partes), 1)}
        if any(p["derivado"] for p in partes):
            props["nome_derivado"] = True
        if any(p.get("aberta") for p in partes):
            props["borda_aberta"] = True
        linhas = [[to_lnglat(x, y) for x, y in p["linha"]] for p in partes]
        feats.append({"type": "Feature", "properties": props, "geometry": (
            {"type": "LineString", "coordinates": linhas[0]} if len(linhas) == 1
            else {"type": "MultiLineString", "coordinates": linhas})})

    # propriedade nula não é ausência para o MapLibre: ["has","name"] dá true
    # e o app acaba pintando pin de POI em área sem nome nenhum.
    for f in feats:
        pr = {k: v for k, v in f["properties"].items() if v is not None}
        # peso = área: rótulo de espaço maior ganha a disputa por espaço na tela
        if "area_m2" in pr:
            pr["peso"] = pr["area_m2"]
        f["properties"] = pr

    json.dump({"type": "FeatureCollection", "features": feats},
              open(OUT, "w"), ensure_ascii=False)

    por = {}
    for f in feats:
        k = f["properties"].get("cat") or f["properties"]["kind"]
        por[k] = por.get(k, 0) + 1
    com_code = sum(1 for f in feats if f["properties"].get("code"))
    com_nome = sum(1 for f in feats if f["properties"].get("name"))
    print(f"features: {len(feats)}  com código: {com_code}  com nome: {com_nome}")
    print("  " + "  ".join(f"{k}={v}" for k, v in sorted(por.items())))


if __name__ == "__main__":
    sys.exit(main())
