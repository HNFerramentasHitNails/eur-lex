#!/usr/bin/env python3
"""Leis portuguesas do Diário da República que transpõem as diretivas do corpus.

Fluxo:
  1. medidas  — pergunta ao Cellar que medidas Portugal comunicou para cada diretiva de
                ferramentas/nucleo.yaml (mais as entradas de ferramentas/dre_extra.yaml) e
                resolve cada uma no DRE pelo identificador europeu ELI (data.dre.pt/eli/...).
  2. obter    — corre ferramentas/dre.js (Chromium) para recolher os dados de cada página.
  3. converter— escreve legislacao-pt/<diploma>.md e legislacao-pt/INDICE.md.
  `tudo` faz os três. Os passos guardam o que obtêm em .cache/dre/, por isso podem repetir-se.

Requer Node.js com o pacote playwright e um Chromium (ver README).
"""

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

import yaml
from bs4 import BeautifulSoup

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import eurlex  # noqa: E402

RAIZ = eurlex.RAIZ
SAIDA = RAIZ / "legislacao-pt"
CACHE = RAIZ / ".cache" / "dre"
EXTRA = RAIZ / "ferramentas" / "dre_extra.yaml"
ELI = "https://data.dre.pt/eli/"
DRE = "https://diariodarepublica.pt"

# Tipo de acto (como o Cellar o regista) -> acrónimo ELI do DRE. Confirmados com pedidos reais.
# Decreto Regulamentar e Lei Orgânica ficam de fora: nenhum dos acrónimos testados resolveu.
ACRONIMOS = {"Lei": "lei", "Decreto-Lei": "dec-lei", "Portaria": "port", "Decreto": "dec"}
# Códigos que o Cellar regista pela sigla: diploma que os aprova.
CODIGOS = {"CT": ("Lei", "7/2009", "2009-02-12"), "CÓDIGO DO TRABALHO - CT": ("Lei", "7/2009", "2009-02-12"),
           "CC": ("Decreto-Lei", "47344/1966", "1966-11-25")}


# ---------------------------------------------------------------------------
# 1. Medidas e resolução
# ---------------------------------------------------------------------------

def diretivas_do_nucleo():
    dados = yaml.safe_load(eurlex.NUCLEO.read_text(encoding="utf-8"))
    res = {}
    for area, info in dados["areas"].items():
        for a in info["actos"]:
            if re.match(r"^3\d{4}L", a["celex"]):
                res[a["celex"]] = {"area": area, "curto": a.get("curto")}
    return res


def medidas_cellar(diretivas):
    vals = " ".join(eurlex._lit(c) for c in diretivas)
    linhas = eurlex.sparql(eurlex.PREFIXOS + f"""
SELECT DISTINCT ?dir ?mc ?tipo ?num ?djo ?d ?t WHERE {{
  VALUES ?dir {{ {vals} }}
  ?base cdm:resource_legal_id_celex ?dir .
  ?m cdm:measure_national_implementing_implements_resource_legal ?base ;
     cdm:measure_national_implementing_implemented_by_country <http://publications.europa.eu/resource/authority/country/PRT> ;
     cdm:resource_legal_id_celex ?mc .
  OPTIONAL {{ ?m cdm:measure_national_implementing_type_act ?tipo }}
  OPTIONAL {{ ?m cdm:resource_legal_id_local ?num }}
  OPTIONAL {{ ?m cdm:measure_national_implementing_date_official_journal ?djo }}
  OPTIONAL {{ ?m cdm:work_date_document ?d }}
  OPTIONAL {{ ?m cdm:work_title ?t }}
}}""")
    return linhas


def _data_valida(d):
    return bool(d) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d[:10] or "") and not d.startswith(("1001", "1900"))


def normalizar(tipo, num, djo, d, titulo):
    """Devolve (tipo, numero 'N/AAAA', data 'AAAA-MM-DD' ou None, motivo_de_exclusão ou None)."""
    tipo = (tipo or "").strip()
    num = (num or "").strip()
    titulo = (titulo or "").strip()
    # O tipo registado no Cellar nem sempre bate com o título (ex.: rectificações como "Portaria").
    if re.match(r"^(Declaração de Re(c)?tificação|De ter sido re(c)?tificad)", titulo, re.I):
        return tipo, num, None, f"declaração de retificação (registada no Cellar como {tipo or '?'})"
    if re.match(r"^Decreto Regulamentar\b", titulo):
        tipo = "Decreto Regulamentar"
    elif re.match(r"^Lei Orgânica\s+n", titulo):
        tipo = "Lei Orgânica"
    # Títulos no formato "Decreto-Lei n° 99 de 27/8/2003": número e data mais fiáveis do que os campos.
    mt = re.match(r"^(Decreto-Lei|Lei|Portaria)\s+n\s*[.°º]*\s*(\d+(?:-[A-Z]{1,2})?)\s+de\s+(\d{1,2})/(\d{1,2})/(\d{4})", titulo)
    if mt and tipo == mt.group(1):
        num = f"{mt.group(2)}/{mt.group(5)}"
        djo = f"{mt.group(5)}-{int(mt.group(4)):02d}-{int(mt.group(3)):02d}"
    chave_codigo = num.upper()
    if tipo in ("Code", "Código") or chave_codigo in CODIGOS:
        if chave_codigo in CODIGOS:
            return (*CODIGOS[chave_codigo], None)
        return tipo, num, None, f"código sem correspondência ({num})"
    if tipo in ("Medidas administrativas", "Administrative measures"):
        return tipo, num, None, "medida administrativa (tipo de acto não identificado)"
    num = re.sub(r"^(Lei|Decreto-Lei|Decreto|Portaria)\s+n\.?\s*º?\s*", "", num, flags=re.I).strip().rstrip(".")
    m = re.fullmatch(r"(\d+(?:-[A-Za-z]{1,2})?)/(\d{2,4})(?:/([AM]))?", num)
    if not m:
        return tipo, num, None, f"número não reconhecido ({num or 'vazio'})"
    if m.group(3):
        return tipo, num, None, "diploma regional (Açores/Madeira)"
    if tipo not in ACRONIMOS:
        return tipo, num, None, f"tipo de acto sem acrónimo ELI conhecido ({tipo})"
    ano = m.group(2)
    if len(ano) == 2:
        ano = ("19" if int(ano) > 30 else "20") + ano
    # Data de publicação: a do título ("Série I de AAAA-MM-DD") primeiro, porque o campo de data
    # do documento no Cellar é muitas vezes a data da notificação à Comissão. Tem de bater com o ano.
    candidatas = []
    mt = re.search(r"S[ée]rie I[-A-Z]*\s+de\s+(\d{4}-\d{2}-\d{2})", titulo)
    if mt:
        candidatas.append(mt.group(1))
    candidatas += [x[:10] for x in (djo, d) if _data_valida(x)]
    data = next((x for x in candidatas if x[:4] == ano), None)
    return tipo, f"{m.group(1).upper()}/{ano}", data, None


def chave(tipo, numero):
    return eurlex.slug(f"{tipo}-{numero.replace('/', '-')}")


def resolver_url(url):
    """Segue os redirecionamentos de um ELI do DRE. Devolve o URL final ou None (página de erro)."""
    for n in range(3):
        try:
            eurlex._esperar("cellar")
            req = urllib.request.Request(url, headers={"User-Agent": eurlex.UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                final = r.geturl()
            return None if "/dr/error" in final else final
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(2 ** (n + 1))
    return None


def resolver(tipo, numero, data):
    ac = ACRONIMOS[tipo]
    n, ano = numero.lower().split("/")
    det = resolver_url(f"{ELI}{ac}/{n}/{ano}/{data[5:7]}/{data[8:10]}/p/dre/pt/html") if data else None
    cons = resolver_url(f"{ELI}{ac}/{n}/{ano}/p/cons/pt/html")
    if cons and "/legislacao-consolidada/" not in cons:
        cons = None
    return det, cons


def cmd_medidas():
    diretivas = diretivas_do_nucleo()
    linhas = medidas_cellar(diretivas)
    medidas = {}
    for l in linhas:
        tipo, numero, data, motivo = normalizar(l.get("tipo"), l.get("num"), l.get("djo", ""),
                                               l.get("d", ""), l.get("t", ""))
        k = chave(tipo, numero) if not motivo else f"_{l['mc']}"
        m = medidas.setdefault(k, {"chave": k, "tipo": tipo, "numero": numero, "data": data,
                                   "excluida": motivo, "titulo_cellar": re.sub(r"\s+", " ", l.get("t", "")).strip(),
                                   "diretivas": [], "celex_medidas": []})
        if l["dir"] not in m["diretivas"]:
            m["diretivas"].append(l["dir"])
        if l["mc"] not in m["celex_medidas"]:
            m["celex_medidas"].append(l["mc"])
        if not m["data"] and data:
            m["data"] = data
    if EXTRA.exists():
        for e in yaml.safe_load(EXTRA.read_text(encoding="utf-8")).get("diplomas", []):
            k = chave(e["tipo"], e["numero"])
            m = medidas.setdefault(k, {"chave": k, "tipo": e["tipo"], "numero": e["numero"], "data": e.get("data"),
                                       "excluida": None, "titulo_cellar": "", "diretivas": [], "celex_medidas": []})
            m.setdefault("relacionado_com", []).extend(e.get("relacionado_com", []))
            m["nota_extra"] = e.get("nota")
    # resolução (com cache)
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_res = CACHE / "resolucao.json"
    feitos = json.loads(cache_res.read_text(encoding="utf-8")) if cache_res.exists() else {}
    for m in sorted(medidas.values(), key=lambda x: x["chave"]):
        if m["excluida"]:
            continue
        cid = f"{m['tipo']}|{m['numero']}|{m['data']}"
        if cid not in feitos:
            det, cons = resolver(m["tipo"], m["numero"], m["data"])
            feitos[cid] = {"detalhe": det, "consolidada": cons}
            cache_res.write_text(json.dumps(feitos, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"{m['chave']:<28} det={'s' if det else '-'} cons={'s' if cons else '-'}", flush=True)
        m.update(feitos[cid])
        if not m["detalhe"] and not m["consolidada"]:
            m["excluida"] = "não encontrado no DRE pelo ELI" + ("" if m["data"] else " (sem data de publicação)")
    SAIDA.mkdir(exist_ok=True)
    (CACHE / "medidas.json").write_text(json.dumps(sorted(medidas.values(), key=lambda x: x["chave"]),
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for m in medidas.values() if not m["excluida"])
    print(f"{len(medidas)} medidas; {ok} resolvidas no DRE; {len(medidas) - ok} excluídas")
    return medidas


# ---------------------------------------------------------------------------
# 2. Recolha (Node + Chromium)
# ---------------------------------------------------------------------------

def cmd_obter(paralelo=2):
    medidas = json.loads((CACHE / "medidas.json").read_text(encoding="utf-8"))
    tarefas = [{"chave": m["chave"], "detalhe": m.get("detalhe") or "", "consolidada": m.get("consolidada") or ""}
               for m in medidas if not m["excluida"]]
    f = CACHE / "tarefas.json"
    f.write_text(json.dumps(tarefas, ensure_ascii=False), encoding="utf-8")
    subprocess.run(["node", str(RAIZ / "ferramentas" / "dre.js"), str(f), str(paralelo)], check=True)


# ---------------------------------------------------------------------------
# 3. Conversão para Markdown
# ---------------------------------------------------------------------------

def _texto_html(t):
    """Texto de um fragmento do DRE: HTML simples com quebras de linha. Devolve parágrafos."""
    t = (t or "").replace("\r\n", "\n").replace("\r", "\n")
    if "<table" in t.lower():
        return eurlex.para_markdown([BeautifulSoup(t.replace("\n", "<br/>"), "lxml").body]).split("\n\n")
    pars = []
    for linha in t.split("\n"):
        linha = BeautifulSoup(linha, "lxml").get_text(" ") if "<" in linha else linha
        linha = re.sub(r"[ \t\xa0]+", " ", linha).strip()
        linha = re.sub(r" ([,.;:)])", r"\1", linha)
        if linha:
            pars.append(linha)
    return pars


def _alteracao(t):
    t = re.sub(r"\[/?L\]", "", t)
    t = BeautifulSoup(t, "lxml").get_text(" ")
    return re.sub(r"\s+", " ", t).replace(" ,", ",").strip()


ESTRUTURA = {"Livro", "Parte", "Título", "Capítulo", "Secção", "Subsecção", "Divisão", "Subdivisão"}


def consolidada_md(dados):
    """Fragmentos da versão consolidada -> Markdown."""
    ls = []
    hoje = dt.date.today().isoformat()
    futuras = set()
    for f in dados["LegConsBase"]["List"]:
        fv = f["FragmentoVersao"]
        tit, epi = (re.sub(r"\s+", " ", BeautifulSoup(x or "", "lxml").get_text(" ")).strip()
                    if "<" in (x or "") else (x or "").strip() for x in (fv["Tituo"], fv["Epigrafe"]))
        epi = re.sub(r" ([,.;:)])", r"\1", epi)
        prox = f.get("DataEntradaVigorProximaVersao", "1900-01-01")
        if prox > hoje:
            futuras.add(prox)
        pars = _texto_html(fv["Texto"])
        if tit == "Diploma":
            ls += pars
        elif tit.startswith("Artigo"):
            ls.append(f"### {eurlex._normalizar_artigo(tit)}" + (f" — {epi}" if epi else ""))
            ls += pars
        elif tit.split(" ")[0] in ESTRUTURA or tit.startswith("Anexo") or tit.startswith("Apêndice"):
            ls.append(f"## {tit}" + (f" — {epi}" if epi else ""))
            ls += pars
        elif tit == "Assinatura":
            ls += pars
        else:
            ls.append(f"**{tit}**" + (f" — {epi}" if epi else ""))
            ls += pars
        for a in f.get("AlteracoesList", {}).get("List", []):
            ls.append("> " + _alteracao(a))
        for n in f.get("Nota", {}).get("List", []):
            ls.append("> Nota: " + _alteracao(n))
    return "\n\n".join(ls), sorted(futuras)


RE_ART_PT = re.compile(r"^Artigo\s+(\d+\.?\s*[ºo°]?(-[A-Z])?|único)\s*$", re.I)


def original_md(texto_formatado, texto):
    """Texto original (sem consolidação): parágrafos HTML com classes de formatação do DRE."""
    if texto_formatado:
        sopa = BeautifulSoup(texto_formatado, "lxml")
        pars = []
        for no in sopa.find_all(["p", "table"]):
            if no.name == "p" and no.find_parent("table"):
                continue
            if no.name == "table":
                pars.append(eurlex.para_markdown([no]))
            else:
                t = re.sub(r"\s+", " ", no.get_text(" ")).strip()
                t = re.sub(r" ([,.;:)])", r"\1", t)
                if t:
                    pars.append(t)
    else:
        pars = _texto_html(texto)
    out, i = [], 0
    while i < len(pars):
        t = pars[i]
        if RE_ART_PT.match(t):
            cab = "### " + eurlex._normalizar_artigo(t.strip())
            if i + 1 < len(pars) and len(pars[i + 1]) < 160 and not re.search(r"[.;:]$", pars[i + 1]) \
                    and not RE_ART_PT.match(pars[i + 1]):
                cab += f" — {pars[i + 1]}"
                i += 1
            out.append(cab)
        elif re.match(r"^(CAPÍTULO|SECÇÃO|TÍTULO|LIVRO|PARTE|ANEXO)\b", t) and len(t) < 60:
            out.append(f"## {t}")
        else:
            out.append(t)
        i += 1
    return "\n\n".join(out)


def cmd_converter():
    medidas = json.loads((CACHE / "medidas.json").read_text(encoding="utf-8"))
    diretivas = diretivas_do_nucleo()
    SAIDA.mkdir(exist_ok=True)
    for f in SAIDA.glob("*.md"):
        f.unlink()
    resumo = []
    for m in medidas:
        if m["excluida"]:
            resumo.append({**m, "estado": "excluída"})
            continue
        c = CACHE / f"{m['chave']}.json"
        if not c.exists():
            resumo.append({**m, "estado": "falhou a recolha"})
            continue
        dados = json.loads(c.read_text(encoding="utf-8"))
        det = (dados.get("detalhe") or {}).get("detalhe", {}).get("DetalheConteudo", {})
        cons = (dados.get("consolidada") or {}).get("consolidada")
        info = ((dados.get("consolidada") or {}).get("consolidadaInfo") or {}).get("ConsolidadaConteudoDetalhe", {})
        if not det and not cons:
            resumo.append({**m, "estado": "falhou a recolha",
                           "excluida": "consolidação não publicada no DRE e ato original não resolvido pelo ELI"})
            continue
        titulo = (det.get("Titulo") or info.get("DiplomaLegis", {}).get("ConteudoTitle") or
                  f"{m['tipo']} n.º {m['numero']}").strip()
        sumario = det.get("Sumario") or info.get("DiplomaLegis", {}).get("Sumario", "")
        vig = det.get("Vigencia") or ""
        revogado = bool(vig) and vig.upper() != "VIGENTE"
        corpo, futuras = ("", [])
        if not revogado:
            if cons:
                corpo, futuras = consolidada_md(cons)
            else:
                corpo = original_md(det.get("TextoFormatado"), det.get("Texto"))
        texto = "revogado (texto não incluído)" if revogado else "consolidado (DRE)" if cons else "original (DRE)"
        fm = {
            "diploma": titulo,
            "tipo": m["tipo"],
            "numero": m["numero"],
            "data_publicacao": (det.get("DataPublicacao") or (info.get("DiplomaLegis", {}).get("DataPublicacao") or "")[:10]
                                or m.get("data")),
            "sumario": sumario,
            "vigencia_dre": vig or None,
            "texto": texto,
            "versao_consolidada_de": cons.get("DataUltimaConsolidada") if cons and not revogado else None,
            "versoes_futuras": futuras or None,
            "transpoe": m["diretivas"] or None,
            "relacionado_com": m.get("relacionado_com") or None,
            "url_dre": m.get("detalhe"),
            "url_consolidada": m.get("consolidada"),
            "eli": (info.get("DiplomaFrag", {}).get("ELI") if cons else None) or det.get("ELI") or None,
            "fonte": "Diário da República Eletrónico (INCM) — diariodarepublica.pt",
            "obtido_em": dados.get("obtido_em"),
        }
        fm = {k: v for k, v in fm.items() if v not in (None, [], "")}
        cab = [f"# {titulo}", "", f"**Sumário:** {sumario}" if sumario else "", ""]
        if m["diretivas"]:
            nomes = []
            for d in m["diretivas"]:
                inf = diretivas.get(d, {})
                nomes.append(f"{d} ({inf.get('curto', '')})" if inf else d)
            cab += ["**Comunicado à Comissão Europeia como transpondo:** " + "; ".join(nomes) + ".", ""]
        if m.get("nota_extra"):
            cab += [f"**Nota:** {m['nota_extra']}", ""]
        if revogado:
            cab += [f"**Vigência segundo o DRE: {vig}.** O texto não foi incluído para não ser lido como "
                    "direito em vigor. Ver o diploma que o substituiu no DRE.", ""]
        elif cons:
            cab += [f"**Texto:** versão consolidada do DRE, última alteração considerada em "
                    f"{cons.get('DataUltimaConsolidada')}. As linhas `> Alterado pelo/a …` indicam a origem "
                    "de cada redacção.", "",
                    "> Aviso do DRE: a edição eletrónica do Diário da República faz fé plena; o texto "
                    "consolidado é produzido pela INCM \"ainda que sem valor legal\". Para efeitos legais, "
                    "confirmar no ato original e nos diplomas que o alteraram.", ""]
        else:
            motivo = ("o DRE regista uma consolidação mas não a tem publicada" if dados.get("consolidada_nao_publicada")
                      else "o DRE não tem versão consolidada deste diploma")
            cab += [f"**Texto:** versão original publicada no DR ({motivo}): **alterações posteriores "
                    "não estão incorporadas** — ver \"Modificações\" na página do DRE.", ""]
        if futuras:
            cab += [f"**Atenção:** há redacções com entrada em vigor futura ({', '.join(futuras)}).", ""]
        cab += [f"**DRE:** {m.get('consolidada') or m.get('detalhe')}", ""]
        if corpo:
            cab += ["## Texto", "", corpo]
        (SAIDA / f"{m['chave']}.md").write_text(eurlex._frontmatter(fm) + "\n".join(cab).strip() + "\n",
                                                encoding="utf-8")
        resumo.append({**m, "estado": texto, "titulo": titulo, "sumario": sumario, "vigencia": vig,
                       "consolidada_de": fm.get("versao_consolidada_de")})
    escrever_indice(resumo, diretivas)
    (SAIDA / "medidas.json").write_text(json.dumps(
        [{k: r.get(k) for k in ("chave", "tipo", "numero", "data", "estado", "excluida", "diretivas",
                                "celex_medidas", "relacionado_com", "titulo", "detalhe", "consolidada")}
         for r in resumo], ensure_ascii=False, indent=1), encoding="utf-8")
    return resumo


def escrever_indice(resumo, diretivas):
    import collections
    est = collections.Counter(r["estado"] for r in resumo)
    ls = ["# Legislação portuguesa de transposição (Diário da República)", "",
          "Diplomas que Portugal comunicou à Comissão Europeia como transpondo as diretivas do corpus "
          "(dados do Cellar), com o texto obtido no Diário da República Eletrónico. Gerado por "
          "`python3 ferramentas/dre.py tudo`.", "",
          "Estado: " + "; ".join(f"{n} {k}" for k, n in est.most_common()) + ".", ""]
    por_dir = collections.defaultdict(list)
    for r in resumo:
        for d in r.get("diretivas") or ["(sem diretiva — entrada manual)"]:
            por_dir[d].append(r)
    for d in sorted(por_dir, key=lambda x: (x.startswith("("), x)):
        inf = diretivas.get(d, {})
        ref = f"[{d}](../corpus/{inf['area']}/)" if inf else d
        ls += [f"## {ref} {inf.get('curto', '')}".rstrip(), ""]
        for r in sorted(por_dir[d], key=lambda x: (x.get("data") or "", x["chave"]), reverse=True):
            if r["estado"] in ("excluída", "falhou a recolha"):
                ls.append(f"- {r['tipo']} {r['numero']} — {r['estado']}: {r.get('excluida') or 'ver registo'}")
            else:
                extra = f", consolidado a {r['consolidada_de']}" if r.get("consolidada_de") else ""
                ls.append(f"- [{r['titulo']}]({r['chave']}.md) — {r['estado']}{extra} — {r.get('sumario', '')[:200]}")
        ls.append("")
    (SAIDA / "INDICE.md").write_text("\n".join(ls), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("passo", choices=["medidas", "obter", "converter", "tudo"])
    ap.add_argument("--paralelo", type=int, default=2)
    a = ap.parse_args()
    if a.passo in ("medidas", "tudo"):
        cmd_medidas()
    if a.passo in ("obter", "tudo"):
        cmd_obter(a.paralelo)
    if a.passo in ("converter", "tudo"):
        r = cmd_converter()
        print(f"{len(r)} medidas processadas")


if __name__ == "__main__":
    main()
