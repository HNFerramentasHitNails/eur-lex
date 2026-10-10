#!/usr/bin/env python3
"""Índices para consulta rápida e barata (em tokens) por IA ou por pessoas.

Gera, a partir do que está em ue/, corpus/ e legislacao-pt/:

  INDICE.md                         guia de entrada (curto) — por onde começar
  indice/actos.tsv                  uma linha por acto: nome popular, tipo, data, estado, temas,
                                    descritores EuroVoc, n.º de artigos, tamanho em tokens, ficheiro
  indice/temas/<cap>.md             actos por área do repertório oficial (20 capítulos)
  indice/eurovoc.tsv                descritor EuroVoc -> actos (índice invertido)
  indice/artigos/<origem>/....tsv   sumário de cada acto: artigo/anexo, epígrafe, linhas, tokens

Os sumários permitem ler só as linhas de um artigo (sed -n 'a,bp' ficheiro) em vez do
ficheiro inteiro. ferramentas/procurar.py usa estes índices.

Uso: python3 ferramentas/indexar.py [--sem-eurovoc]
"""

import argparse
import collections
import csv
import datetime as dt
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import eurlex  # noqa: E402

RAIZ = eurlex.RAIZ
IND = RAIZ / "indice"
CACHE_EV = RAIZ / ".cache" / "eurovoc.json"
csv.field_size_limit(10 ** 9)

RE_CAB = re.compile(r"^(#{2,3}) (.+?)\s*$")
RE_UNIDADE = re.compile(r"^(Artigo|Article|ANEXO|ANNEX|Anexo|APÊNDICE|Apêndice|Preâmbulo|PROTOCOLO|Protocolo)\b")


def tokens(n_chars):
    """Estimativa grosseira: ~4 caracteres por token em português."""
    return max(1, round(n_chars / 4))


# ---------------------------------------------------------------------------
# EuroVoc
# ---------------------------------------------------------------------------

def obter_eurovoc():
    """celex -> [descritores EuroVoc em PT], para os actos em vigor. Guardado em cache."""
    if CACHE_EV.exists():
        return json.loads(CACHE_EV.read_text(encoding="utf-8"))
    ev = {}
    for sector in "1234":
        for ano in range(1951, dt.date.today().year + 1):
            linhas = eurlex.sparql(eurlex.PREFIXOS + f"""
SELECT ?celex (GROUP_CONCAT(DISTINCT ?l; separator="|") AS ?termos) WHERE {{
  ?w cdm:resource_legal_in-force "true"^^xsd:boolean ; cdm:resource_legal_id_celex ?celex .
  FILTER(STRSTARTS(STR(?celex), "{sector}{ano}"))
  ?w cdm:work_is_about_concept_eurovoc ?c .
  ?c skos:prefLabel ?l . FILTER(lang(?l) = "pt")
}} GROUP BY ?celex""")
            for l in linhas:
                ev[l["celex"]] = sorted(set(l["termos"].split("|")))
    CACHE_EV.parent.mkdir(parents=True, exist_ok=True)
    CACHE_EV.write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")
    return ev


# ---------------------------------------------------------------------------
# Nome popular
# ---------------------------------------------------------------------------

RE_POPULAR = re.compile(r"\(([^()]{6,120})\)")
EXCLUIR_POP = re.compile(r"(Texto relevante|EEE|reformulação|codificação|versão codificada|JO |^\d|C\(\d)", re.I)


def nome_popular(titulo, curto=None):
    """'(Regulamento Geral sobre a Proteção de Dados)' -> nome popular; senão o início do título."""
    if curto:
        return curto
    for m in RE_POPULAR.finditer(titulo or ""):
        t = m.group(1).strip()
        if not EXCLUIR_POP.search(t) and re.search(r"[A-Za-zÀ-ú]{4}", t):
            return t
    return ""


def titulo_curto(titulo, n=140):
    t = re.sub(r"\s*\(Texto relevante para efeitos do EEE\.?\)", "", titulo or "")
    return t if len(t) <= n else t[: n - 1] + "…"


# ---------------------------------------------------------------------------
# Sumário de um ficheiro
# ---------------------------------------------------------------------------

IGNORAR_CAB = {"Texto", "Alterações incorporadas", "Alterações incorporadas nesta versão"}


def sumario(caminho):
    """Unidades de leitura de um ficheiro: artigos (###), anexos/preâmbulo/protocolos (##), com as
    linhas onde começam e acabam e o tamanho. Os capítulos e secções não contam como unidade."""
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    cabs = [(i, len(m.group(1)), m.group(2)) for i, l in enumerate(linhas, 1) if (m := RE_CAB.match(l))]
    res = []
    for k, (i, nivel, t) in enumerate(cabs):
        if t in IGNORAR_CAB or (nivel == 2 and not RE_UNIDADE.match(t)):
            continue
        fim = len(linhas)
        for j, nv2, _ in cabs[k + 1:]:
            if nv2 <= nivel:
                fim = j - 1
                break
        while fim > i and not linhas[fim - 1].strip():
            fim -= 1
        partes = t.split(" — ", 1)
        res.append({"unidade": partes[0], "epigrafe": partes[1] if len(partes) > 1 else "",
                    "tipo": "artigo" if nivel == 3 else "anexo", "ini": i, "fim": fim,
                    "chars": sum(len(x) + 1 for x in linhas[i - 1:fim])})
    return res, sum(len(x) + 1 for x in linhas)


# ---------------------------------------------------------------------------
# Recolha
# ---------------------------------------------------------------------------

def ficheiros_ue():
    """(celex, caminho principal, [partes]) de ue/ a partir de ue/INDICE.tsv."""
    f = RAIZ / "ue" / "INDICE.tsv"
    with open(f, encoding="utf-8", newline="") as fh:
        for l in csv.DictReader(fh, delimiter="\t"):
            p = RAIZ / l["ficheiro"]
            if p.exists():
                yield l, p


def construir(com_eurovoc=True):
    IND.mkdir(exist_ok=True)
    ev = obter_eurovoc() if com_eurovoc else {}
    catalogo = {}
    with open(eurlex.CATALOGO / "legislacao-em-vigor.tsv", encoding="utf-8", newline="") as fh:
        for l in csv.DictReader(fh, delimiter="\t"):
            catalogo[l["celex"]] = l
    rotulos = {}
    for l in (eurlex.CATALOGO / "repertorio.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*- `([\d.]+)` (.+?) — \d+ actos?$", l)
        if m:
            rotulos[m.group(1)] = m.group(2)
    lista = json.loads((RAIZ / ".cache" / "ue" / "lista.json").read_text(encoding="utf-8")) \
        if (RAIZ / ".cache" / "ue" / "lista.json").exists() else {}
    # corpus curado e leis portuguesas
    curado = {}
    for f in sorted(eurlex.CORPUS.glob("*/*.md")):
        if f.parent.name.startswith("_") or f.name.endswith((".considerandos.md", ".contexto.md")):
            continue
        fm = eurlex.ler_frontmatter(f)
        if fm.get("celex"):
            curado[fm["celex"]] = (f, fm)
    pt_por_dir = collections.defaultdict(list)
    medidas = RAIZ / "legislacao-pt" / "medidas.json"
    if medidas.exists():
        for m in json.loads(medidas.read_text(encoding="utf-8")):
            if m.get("estado") in (None, "excluída", "falhou a recolha"):
                continue
            for d in (m.get("diretivas") or []) + (m.get("relacionado_com") or []):
                pt_por_dir[d].append(m["chave"])

    artigos_dir = IND / "artigos"
    if artigos_dir.exists():
        for f in artigos_dir.rglob("*.tsv"):
            f.unlink()
    escritores = {}

    def escrever_artigos(grupo, celex, ficheiro, unidades):
        destino = artigos_dir / f"{grupo}.tsv"
        if grupo not in escritores:
            destino.parent.mkdir(parents=True, exist_ok=True)
            fh = open(destino, "w", encoding="utf-8", newline="")
            w = csv.writer(fh, delimiter="\t", lineterminator="\n")
            w.writerow(["celex", "unidade", "epigrafe", "linha_ini", "linha_fim", "tokens", "ficheiro"])
            escritores[grupo] = (fh, w)
        w = escritores[grupo][1]
        for u in unidades:
            w.writerow([celex, u["unidade"], u.get("epigrafe", "")[:160], u["ini"], u["fim"], tokens(u["chars"]),
                        ficheiro])

    actos = []
    # 1) ue/
    for l, p in ficheiros_ue():
        c = l["celex"]
        cat = catalogo.get(c, {})
        info = lista.get(c, {})
        titulo = cat.get("titulo") or info.get("titulo") or ""
        cur = curado.get(c)
        unidades, total = [], 0
        for parte in [p] + sorted(p.parent.glob(p.name[:-3] + ".parte-*.md")):
            u, t = sumario(parte)
            rel = str(parte.relative_to(RAIZ))
            escrever_artigos(f"ue/{eurlex_pasta(c)}", c, rel, u)
            unidades += u
            total += t
        n_art = sum(1 for u in unidades if u["tipo"] == "artigo")
        rep = (cat.get("repertorio") or info.get("repertorio") or "").split()
        actos.append({
            "celex": c,
            "nome": nome_popular(titulo, cur[1].get("nome_curto") if cur else None),
            "titulo": titulo_curto(titulo),
            "tipo": cat.get("tipo") or eurlex.nome_tipo(c),
            "data": cat.get("data") or info.get("data", ""),
            "estado": l["estado"],
            "texto": l["texto"],
            "temas": " | ".join(rotulos.get(x, x) for x in rep[:3]),
            "repertorio": " ".join(rep),
            "eurovoc": " | ".join(ev.get(c, [])[:12]),
            "artigos": n_art,
            "tokens": tokens(total),
            "ficheiro": l["ficheiro"],
            "curado": str(cur[0].relative_to(RAIZ)) if cur else "",
            "leis_pt": " ".join(f"legislacao-pt/{k}.md" for k in pt_por_dir.get(c, [])),
        })
    # 2) corpus curado (sumários)
    for c, (f, fm) in curado.items():
        u, _ = sumario(f)
        escrever_artigos("corpus", c, str(f.relative_to(RAIZ)), u)
    # 3) legislação portuguesa
    for f in sorted((RAIZ / "legislacao-pt").glob("*.md")):
        if f.name == "INDICE.md":
            continue
        u, _ = sumario(f)
        escrever_artigos("legislacao-pt", f.stem, str(f.relative_to(RAIZ)), u)
    for fh, _ in escritores.values():
        fh.close()

    campos = ["celex", "nome", "titulo", "tipo", "data", "estado", "texto", "temas", "repertorio", "eurovoc",
              "artigos", "tokens", "ficheiro", "curado", "leis_pt"]
    with open(IND / "actos.tsv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(campos)
        for a in sorted(actos, key=lambda x: x["celex"]):
            w.writerow([str(a[k]).replace("\t", " ").replace("\n", " ") for k in campos])

    escrever_eurovoc(actos)
    escrever_temas(actos, rotulos)
    escrever_entrada(actos, curado)
    return len(actos)


def eurlex_pasta(celex):
    from completo import pasta
    return pasta(celex)


def _prioridade(a):
    """Ordem dentro de um tema: curados, depois regulamentos/diretivas, depois mais recentes."""
    tipo = {"Regulamento": 0, "Diretiva": 0, "Tratado": 1, "Decisão": 2}.get(a["tipo"], 3)
    return (0 if a["curado"] else 1, tipo, "" if not a["data"] else "".join(chr(255 - ord(x)) for x in a["data"]))


def escrever_eurovoc(actos):
    inv = collections.defaultdict(list)
    for a in actos:
        for t in filter(None, a["eurovoc"].split(" | ")):
            inv[t].append(a)
    with open(IND / "eurovoc.tsv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["descritor", "n_actos", "actos (curados e regulamentos/diretivas primeiro)"])
        for t in sorted(inv, key=lambda x: x.lower()):
            lst = sorted(inv[t], key=_prioridade)
            w.writerow([t, len(lst), " ".join(a["celex"] for a in lst[:300])])


def escrever_temas(actos, rotulos):
    pasta = IND / "temas"
    if pasta.exists():
        for f in pasta.glob("*.md"):
            f.unlink()
    pasta.mkdir(parents=True, exist_ok=True)
    por_cod = collections.defaultdict(list)
    for a in actos:
        for cod in set(a["repertorio"].split()):
            if not re.fullmatch(r"\d\d(\.\d\d)*", cod):
                continue  # códigos fora do repertório numérico (raros)
            nivel3 = ".".join(cod.split(".")[:3])
            por_cod[nivel3].append(a)
    caps = sorted({c.split(".")[0] for c in por_cod})
    for cap in caps:
        ls = [f"# {cap} — {rotulos.get(cap, '')}", "",
              "Actos em vigor desta área (repertório oficial do EUR-Lex), por subárea. Em cada subárea: "
              "primeiro os do corpus curado, depois regulamentos e diretivas, depois os mais recentes. "
              "Formato: `CELEX` · nome · tipo e data · ≈tokens · ficheiro.", ""]
        for cod in sorted((c for c in por_cod if c.split(".")[0] == cap),
                          key=lambda x: [int(p) for p in x.split(".")]):
            lst = sorted(por_cod[cod], key=_prioridade)
            ls += [f"## `{cod}` {rotulos.get(cod, '')} ({len(lst)})", ""]
            for a in lst:
                nome = a["nome"] or a["titulo"][:90]
                ls.append(f"- `{a['celex']}` · {nome} · {a['tipo']} {a['data'][:4]} · ≈{a['tokens']} · "
                          f"{a['curado'] or a['ficheiro']}")
            ls.append("")
        (pasta / f"{cap}.md").write_text("\n".join(ls), encoding="utf-8")


def escrever_entrada(actos, curado):
    c = collections.Counter(a["tipo"] for a in actos)
    est = collections.Counter(a["estado"] for a in actos)
    rot = {}
    for l in (eurlex.CATALOGO / "repertorio.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^- `(\d\d)` (.+?) — (\d+) actos?$", l)
        if m:
            rot[m.group(1)] = (m.group(2), m.group(3))
    ls = [
        "# Índice — por onde começar", "",
        f"Gerado por `python3 ferramentas/indexar.py` em {dt.date.today().isoformat()}. "
        f"{len(actos)} actos da UE ({est.get('em vigor', 0)} em vigor, {est.get('em vigor (por confirmar)', 0)} em vigor por "
        f"confirmar no Cellar, {est.get('futuro', 0)} futuros), "
        f"{len(curado)} no corpus curado, leis portuguesas de transposição em `legislacao-pt/`.", "",
        "## Para gastar poucos tokens", "",
        "1. **Não abras ficheiros inteiros.** Um regulamento pode ter 50 000+ tokens; um artigo tem 200–2 000.",
        "2. **Encontra o acto**: `python3 ferramentas/procurar.py actos <palavras>` (nome popular, título, temas, "
        "EuroVoc) ou `rg -i '<palavra>' indice/actos.tsv | cut -f1,2,3,13`.",
        "3. **Vê o sumário do acto**: `python3 ferramentas/procurar.py artigos <CELEX>` (artigos, epígrafes, "
        "linhas e tokens de cada um).",
        "4. **Lê só o artigo**: `python3 ferramentas/procurar.py ler <CELEX> 6` (ou `sed -n '<ini>,<fim>p' "
        "<ficheiro>` com as linhas do sumário).",
        "5. **Não sabes o acto?** Pesquisa no texto: `python3 ferramentas/procurar.py texto \"<pergunta>\"` "
        "(devolve os artigos mais relevantes de toda a legislação; constrói o índice local na 1.ª vez).",
        "6. **Empresa em Portugal + diretiva**: `python3 ferramentas/procurar.py pt <CELEX da diretiva>` dá a "
        "lei portuguesa que a transpõe.", "",
        "## Índices", "",
        "| Ficheiro | Para quê |", "|---|---|",
        "| `indice/actos.tsv` | Uma linha por acto: `celex`, `nome` popular, `titulo`, `tipo`, `data`, `estado`, "
        "`texto`, `temas`, `repertorio`, `eurovoc`, `artigos`, `tokens`, `ficheiro`, `curado`, `leis_pt`. |",
        "| `indice/temas/<cap>.md` | Actos por área do repertório (capítulos abaixo). |",
        "| `indice/eurovoc.tsv` | Descritor temático EuroVoc → actos. Bom para sinónimos e temas transversais. |",
        "| `indice/artigos/…/*.tsv` | Sumário de cada acto: unidade (artigo/anexo), epígrafe, linhas, tokens. "
        "Pesquisar epígrafes em toda a legislação: `rg -i 'direito de retratação' indice/artigos`. |",
        "| `corpus/INDICE.md` | Os actos curados (com considerandos, sínteses, transposição, jurisprudência). |",
        "| `legislacao-pt/INDICE.md` | Leis portuguesas por diretiva. |",
        "| `catalogo/legislacao-em-vigor.tsv` | Catálogo completo com ELI e ligações. |", "",
        "## Áreas (repertório oficial do EUR-Lex)", "",
    ]
    for cap, (nome, n) in sorted(rot.items()):
        ls.append(f"- [`{cap}` {nome}](indice/temas/{cap}.md) — {n} actos")
    ls += ["", "## Actos curados mais pedidos", ""]
    for c_, (f, fm) in sorted(curado.items(), key=lambda x: str(x[1][0])):
        ls.append(f"- `{c_}` {fm.get('nome_curto', '')} — `{f.relative_to(RAIZ)}`")
    ls += ["", f"Tipos de acto: " + "; ".join(f"{k} {v}" for k, v in c.most_common()) + "."]
    (RAIZ / "INDICE.md").write_text("\n".join(ls) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sem-eurovoc", action="store_true")
    ap.add_argument("--so-eurovoc", action="store_true", help="só descarregar os descritores EuroVoc")
    a = ap.parse_args()
    if a.so_eurovoc:
        print(f"{len(obter_eurovoc())} actos com descritores EuroVoc")
        return
    print(f"{construir(not a.sem_eurovoc)} actos indexados")


if __name__ == "__main__":
    main()
