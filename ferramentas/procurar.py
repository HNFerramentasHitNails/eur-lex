#!/usr/bin/env python3
"""Consulta dirigida da legislação: devolve só o que é preciso, para gastar poucos tokens.

  procurar.py actos <palavras…>        actos por nome popular, título, número, temas e EuroVoc
  procurar.py artigos <CELEX> [filtro]  sumário do acto: artigos/anexos, epígrafes, linhas, tokens
  procurar.py ler <CELEX> <artigo>      texto de um artigo (ex.: 6, 6-A, "anexo I", preambulo)
  procurar.py texto "<pergunta>"        artigos mais relevantes em toda a legislação (BM25)
  procurar.py pt <CELEX>                leis portuguesas ligadas a uma diretiva/regulamento
  procurar.py construir                 (re)constrói o índice de texto local (.cache/procurar.sqlite)

<CELEX> pode ser também uma lei portuguesa pela chave (ex.: decreto-lei-24-2014).
Opções comuns: --n N (resultados), --fonte ue|corpus|pt (texto), --tipo regulamentos|diretivas|…
"""

import argparse
import csv
import json
import pathlib
import re
import sqlite3
import sys
import unicodedata

RAIZ = pathlib.Path(__file__).resolve().parent.parent
IND = RAIZ / "indice"
BD = RAIZ / ".cache" / "procurar.sqlite"
csv.field_size_limit(10 ** 9)
sys.path.insert(0, str(RAIZ / "ferramentas"))

PARAGENS = set("""a o as os de da do das dos e em no na nos nas um uma uns umas que se por para com sem
ao aos à às é ser são ou como mais menos qual quais quando onde quem sobre entre até pelo pela pelos pelas
este esta estes estas esse essa isso isto meu minha seu sua seus suas lhe lhes já não sim também tem têm
há posso pode podem devo deve devem preciso precisa qualquer cada the of and to in for""".split())


def norm(t):
    """Minúsculas, sem acentos e com a grafia anterior ao Acordo Ortográfico unificada
    (retractação/retratação, excepção/exceção, adoptar/adotar), igual na pesquisa e no índice."""
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"c(?=[tc])|p(?=[tc])", "", t)
    return re.sub(r"[^a-z0-9/.\-]+", " ", t).strip()


def termos(consulta):
    return [w for w in norm(consulta).split() if w not in PARAGENS and len(w) > 1]


def ler_tsv(caminho):
    with open(caminho, encoding="utf-8", newline="") as fh:
        yield from csv.DictReader(fh, delimiter="\t")


# ---------------------------------------------------------------------------
# actos
# ---------------------------------------------------------------------------

def cmd_actos(consulta, n=15, tipo=None):
    ts = termos(" ".join(consulta))
    res = []
    for a in ler_tsv(IND / "actos.tsv"):
        if tipo and f"/{tipo}/" not in "/" + a["ficheiro"]:
            continue
        campos = {"celex": norm(a["celex"]), "nome": norm(a["nome"]), "titulo": norm(a["titulo"]),
                  "eurovoc": norm(a["eurovoc"]), "temas": norm(a["temas"])}
        pont, encontrados = 0.0, 0
        for t in ts:
            hit = False
            for campo, peso in (("celex", 10), ("nome", 6), ("titulo", 2), ("eurovoc", 2), ("temas", 1)):
                if t in campos[campo]:
                    pont += peso
                    hit = True
            encontrados += hit
        if not encontrados:
            continue
        pont *= (encontrados / len(ts)) ** 2  # privilegia actos que têm todas as palavras
        pont += 6 if a["curado"] else 0
        pont += 3 if a["nome"] else 0  # actos com nome popular são os principais
        pont += 2 if a["tipo"] in ("Regulamento", "Diretiva") else 0
        pont -= 2 if re.search(r"\bque altera\b|\balterando\b", a["titulo"]) else 0
        pont -= 1 if a["tipo"] == "Decisão sobre concentração" else 0
        res.append((pont, a))
    res.sort(key=lambda x: (-x[0], x[1]["data"]), reverse=False)
    for _, a in res[:n]:
        nome = a["nome"] or a["titulo"]
        extra = f" · curado: {a['curado']}" if a["curado"] else ""
        pt = f" · leis PT: {len(a['leis_pt'].split())}" if a["leis_pt"] else ""
        print(f"{a['celex']} · {nome[:110]} · {a['tipo']} {a['data'][:4]} · {a['artigos']} art. · "
              f"≈{a['tokens']} tok · {a['ficheiro']}{extra}{pt}")
    if not res:
        print("Nada encontrado. Tenta sinónimos, o número do acto (ex.: 2016/679) ou `procurar.py texto`.")


# ---------------------------------------------------------------------------
# sumário e leitura
# ---------------------------------------------------------------------------

def _acto(celex):
    for a in ler_tsv(IND / "actos.tsv"):
        if a["celex"] == celex:
            return a
    return None


def unidades(chave, fonte=None):
    """Unidades (artigos/anexos) de um acto: do corpus curado se existir, senão de ue/; ou de uma
    lei portuguesa (chave tipo-numero-ano)."""
    if re.match(r"^[a-z]", chave):
        grupos = ["legislacao-pt"]
    else:
        from completo import pasta
        grupos = ([] if fonte == "ue" else ["corpus"]) + ([] if fonte == "corpus" else [f"ue/{pasta(chave)}"])
    for g in grupos:
        f = IND / "artigos" / f"{g}.tsv"
        if not f.exists():
            continue
        us = [u for u in ler_tsv(f) if u["celex"] == chave]
        if us:
            return us
    return []


def cmd_artigos(chave, filtro=None, fonte=None):
    us = unidades(chave, fonte)
    if not us:
        print(f"Sem sumário para {chave}. Confirma o CELEX com `procurar.py actos`.")
        return
    fv = norm(filtro) if filtro else None
    print(f"{chave} — {us[0]['ficheiro']}")
    for u in us:
        if fv and fv not in norm(u["unidade"] + " " + u["epigrafe"]):
            continue
        print(f"  {u['unidade']}{' — ' + u['epigrafe'] if u['epigrafe'] else ''}  "
              f"[linhas {u['linha_ini']}-{u['linha_fim']}, ≈{u['tokens']} tok]")


def _alvo(artigo):
    a = norm(artigo).replace(" ", "")
    if a.startswith("anexo") or a.startswith("annex"):
        return "anexo", a.replace("annex", "anexo")
    if a.startswith("pre"):
        return "preambulo", "preambulo"
    m = re.match(r"^(?:artigo|art\.?)?(\d+)(?:\.?o)?(?:-?([a-z]))?$", a)
    if m:
        return "artigo", f"artigo{m.group(1)}" + (f"-{m.group(2)}" if m.group(2) else "")
    return "outro", a


def cmd_ler(chave, artigo, fonte=None):
    tipo, alvo = _alvo(artigo)
    for u in unidades(chave, fonte):
        nome = norm(u["unidade"]).replace(" ", "").replace(".o", "").replace("o-", "-")
        nome = re.sub(r"^artigo(\d+)o?", r"artigo\1", nome)
        if nome == alvo or (tipo == "anexo" and nome == alvo) or (tipo == "outro" and alvo in nome):
            linhas = (RAIZ / u["ficheiro"]).read_text(encoding="utf-8").splitlines()
            print(f"<!-- {u['ficheiro']}:{u['linha_ini']}-{u['linha_fim']} -->")
            print("\n".join(linhas[int(u["linha_ini"]) - 1:int(u["linha_fim"])]))
            return
    print(f"Não encontrei '{artigo}' em {chave}. Vê `procurar.py artigos {chave}`.")


# ---------------------------------------------------------------------------
# leis portuguesas
# ---------------------------------------------------------------------------

def cmd_pt(celex):
    f = RAIZ / "legislacao-pt" / "medidas.json"
    if not f.exists():
        print("Sem legislacao-pt/medidas.json.")
        return
    achou = False
    for m in json.loads(f.read_text(encoding="utf-8")):
        if celex in (m.get("diretivas") or []) + (m.get("relacionado_com") or []):
            achou = True
            if m.get("estado") in ("excluída", "falhou a recolha"):
                print(f"  {m['tipo']} {m['numero']} — não obtido: {m.get('excluida')}")
            else:
                print(f"  {m.get('titulo') or m['chave']} — {m['estado']} — legislacao-pt/{m['chave']}.md")
    if not achou:
        print(f"Nenhuma lei portuguesa registada para {celex} (o Cellar só regista transposição de diretivas).")


# ---------------------------------------------------------------------------
# texto integral (SQLite FTS5, construído localmente)
# ---------------------------------------------------------------------------

LIMITE_UNIDADE = 200_000  # caracteres indexados por unidade (anexos gigantes)


def cmd_construir():
    BD.parent.mkdir(parents=True, exist_ok=True)
    if BD.exists():
        BD.unlink()
    con = sqlite3.connect(BD)
    con.executescript("""
      PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
      CREATE TABLE meta(id INTEGER PRIMARY KEY, celex TEXT, unidade TEXT, epigrafe TEXT, ficheiro TEXT,
                        ini INT, fim INT, tokens INT, fonte TEXT);
      CREATE VIRTUAL TABLE u USING fts5(epigrafe, texto, content='', tokenize='unicode61 remove_diacritics 2');
    """)
    n = 0
    for f in sorted((IND / "artigos").rglob("*.tsv")):
        fonte = "corpus" if f.stem == "corpus" else "pt" if f.stem == "legislacao-pt" else "ue"
        cache = {}
        lote_m, lote_u = [], []
        for u in ler_tsv(f):
            fich = u["ficheiro"]
            if fich not in cache:
                cache.clear()
                cache[fich] = (RAIZ / fich).read_text(encoding="utf-8").splitlines()
            linhas = cache[fich]
            texto = "\n".join(linhas[int(u["linha_ini"]):int(u["linha_fim"])])[:LIMITE_UNIDADE]
            n += 1
            lote_m.append((n, u["celex"], u["unidade"], u["epigrafe"], fich, int(u["linha_ini"]),
                           int(u["linha_fim"]), int(u["tokens"]), fonte))
            lote_u.append((n, norm(u["unidade"] + " " + u["epigrafe"]), norm(texto)))
        con.executemany("INSERT INTO meta VALUES (?,?,?,?,?,?,?,?,?)", lote_m)
        con.executemany("INSERT INTO u(rowid, epigrafe, texto) VALUES (?,?,?)", lote_u)
        con.commit()
    # actos sem artigos (ex.: decisões em forma de carta): indexa-se o texto inteiro como uma unidade
    for a in ler_tsv(IND / "actos.tsv"):
        if a["artigos"] != "0" or not (RAIZ / a["ficheiro"]).exists():
            continue
        t = (RAIZ / a["ficheiro"]).read_text(encoding="utf-8")
        n += 1
        con.execute("INSERT INTO meta VALUES (?,?,?,?,?,?,?,?,?)",
                    (n, a["celex"], "texto", a["nome"] or a["titulo"][:100], a["ficheiro"], 1,
                     t.count("\n") + 1, int(a["tokens"]), "ue"))
        con.execute("INSERT INTO u(rowid, epigrafe, texto) VALUES (?,?,?)",
                    (n, norm(a["nome"] + " " + a["titulo"]), norm(t[:LIMITE_UNIDADE])))
    con.commit()
    con.execute("INSERT INTO u(u) VALUES('optimize')")
    con.commit()
    con.close()
    print(f"{n} unidades indexadas em {BD.relative_to(RAIZ)} ({BD.stat().st_size // 2**20} MB)")


def _excerto(ficheiro, ini, fim, ts, largura=220):
    linhas = (RAIZ / ficheiro).read_text(encoding="utf-8").splitlines()[ini:fim]
    melhor, pont = "", -1
    for l in linhas:
        n = sum(1 for t in ts if t in norm(l))
        if n > pont:
            melhor, pont = l, n
    melhor = re.sub(r"\s+", " ", melhor).strip()
    return melhor[:largura] + ("…" if len(melhor) > largura else "")


def cmd_texto(consulta, n=10, fonte=None, tipo=None):
    if not BD.exists():
        print("Índice de texto inexistente; a construir (uma vez, alguns minutos)…", file=sys.stderr)
        cmd_construir()
    ts = termos(consulta)
    if not ts:
        print("Consulta vazia.")
        return
    # OR entre termos (bm25 ordena por quantos e quão raros); prefixo para apanhar flexões (retrat*)
    q = " OR ".join(f'"{t}"*' if len(t) > 4 else f'"{t}"' for t in ts)
    con = sqlite3.connect(BD)
    filtros, args = [], [q]
    if fonte:
        filtros.append("m.fonte = ?")
        args.append(fonte)
    if tipo:
        filtros.append("m.ficheiro LIKE ?")
        args.append(f"ue/{tipo}/%")
    sql = ("SELECT m.celex, m.unidade, m.epigrafe, m.ficheiro, m.ini, m.fim, m.tokens, m.fonte, "
           "bm25(u, 4.0, 1.0) AS r FROM u JOIN meta m ON m.id = u.rowid WHERE u MATCH ? "
           + ("AND " + " AND ".join(filtros) if filtros else "") + " ORDER BY r LIMIT ?")
    args.append(n * 3)
    vistos, saida = set(), []
    for celex, unidade, epi, fich, ini, fim, tok, fnt, r in con.execute(sql, args):
        chave = (celex, unidade)
        if chave in vistos:  # o mesmo artigo no corpus curado e em ue/: fica o primeiro
            continue
        vistos.add(chave)
        saida.append((celex, unidade, epi, fich, ini, fim, tok, fnt))
        if len(saida) >= n:
            break
    for celex, unidade, epi, fich, ini, fim, tok, fnt in saida:
        print(f"{celex} · {unidade}{' — ' + epi[:90] if epi else ''} · {fich}:{ini}-{fim} · ≈{tok} tok")
        print(f"    {_excerto(fich, ini - 1, fim, ts)}")
    if not saida:
        print("Nada encontrado no texto. Tenta outras palavras ou `procurar.py actos`.")


def main():
    import signal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # permitir `| head` sem erro
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("comando", choices=["actos", "artigos", "ler", "texto", "pt", "construir"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--n", type=int, default=None)
    ap.add_argument("--fonte", choices=["ue", "corpus", "pt"])
    ap.add_argument("--tipo")
    a = ap.parse_args()
    if a.comando == "actos":
        cmd_actos(a.args, a.n or 15, a.tipo)
    elif a.comando == "artigos":
        cmd_artigos(a.args[0], " ".join(a.args[1:]) or None, a.fonte if a.fonte in ("ue", "corpus") else None)
    elif a.comando == "ler":
        cmd_ler(a.args[0], " ".join(a.args[1:]), a.fonte if a.fonte in ("ue", "corpus") else None)
    elif a.comando == "texto":
        cmd_texto(" ".join(a.args), a.n or 10, a.fonte, a.tipo)
    elif a.comando == "pt":
        cmd_pt(a.args[0])
    elif a.comando == "construir":
        cmd_construir()


if __name__ == "__main__":
    main()
