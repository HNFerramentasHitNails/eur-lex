#!/usr/bin/env python3
"""Extrai legislação da UE do EUR-Lex e converte-a para Markdown legível pelo Claude.

Fonte: Cellar, o repositório oficial do Serviço das Publicações da União Europeia
(publications.europa.eu), que é onde o EUR-Lex vai buscar os textos. Usa-se o Cellar
em vez de raspar o site eur-lex.europa.eu porque o robots.txt do EUR-Lex pede 10 s
entre pedidos; o site só é usado como último recurso, respeitando essa pausa.

Comandos:
  obter CELEX [CELEX ...] [--area AREA]   descarrega actos avulsos
  nucleo [--so CELEX ...]                 descarrega a lista curada (ferramentas/nucleo.yaml)
  catalogo                                gera o catálogo de toda a legislação em vigor
  indice                                  regenera corpus/INDICE.md a partir dos ficheiros
"""

import argparse
import csv
import datetime as dt
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import warnings

import yaml
from bs4 import BeautifulSoup, Comment, NavigableString, Tag, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

RAIZ = pathlib.Path(__file__).resolve().parent.parent
CORPUS = RAIZ / "corpus"
CATALOGO = RAIZ / "catalogo"
NUCLEO = RAIZ / "ferramentas" / "nucleo.yaml"

SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
CELLAR = "https://publications.europa.eu/resource/celex/"
EURLEX = "https://eur-lex.europa.eu/legal-content/{lg}/TXT/{fmt}/?uri=CELEX:{celex}"
UA = "eur-lex-corpus/1.0 (+https://github.com/HNFerramentasHitNails/eur-lex)"
PAUSA_CELLAR = 1.0
PAUSA_EURLEX = 10.0  # Crawl-delay do robots.txt do EUR-Lex

LINGUA = {"pt": ("PT", "por", "POR"), "en": ("EN", "eng", "ENG")}

# Letra de tipo no CELEX do sector 3 (legislação derivada); confirmado pelos títulos no Cellar.
TIPOS_3 = {
    "R": "Regulamento", "L": "Diretiva", "D": "Decisão", "H": "Recomendação", "A": "Parecer",
    "M": "Decisão sobre concentração", "J": "Decisão sobre concentração", "O": "Orientação (BCE)",
    "E": "Ação ou posição comum (PESC)", "F": "Decisão-quadro", "G": "Resolução", "B": "Orçamento",
    "S": "Decisão CECA", "K": "Recomendação CECA", "Q": "Acto interno de instituição ou órgão",
}
TIPOS_SECTOR = {"1": "Tratado", "2": "Acordo internacional", "4": "Acto complementar",
                "6": "Jurisprudência", "5": "Acto preparatório", "7": "Medida nacional de transposição"}

_ultimo_pedido = {"cellar": 0.0, "eurlex": 0.0}


# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------

class SemRedirecionar(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_abridor = urllib.request.build_opener(SemRedirecionar)


def _esperar(origem):
    pausa = PAUSA_EURLEX if origem == "eurlex" else PAUSA_CELLAR
    falta = _ultimo_pedido[origem] + pausa - time.monotonic()
    if falta > 0:
        time.sleep(falta)
    _ultimo_pedido[origem] = time.monotonic()


def http_get(url, headers=None, origem="cellar", timeout=300, tentativas=4):
    """GET que segue redirecionamentos à mão (o Cellar redireciona para http://,
    que forçamos para https://). Devolve (estado, content-type, corpo)."""
    cab = {"User-Agent": UA}
    cab.update(headers or {})
    for salto in range(10):
        url = re.sub(r"^http://", "https://", url)
        for n in range(tentativas):
            _esperar(origem)
            try:
                resp = _abridor.open(urllib.request.Request(url, headers=cab), timeout=timeout)
                return resp.status, resp.headers.get("Content-Type", ""), resp.read()
            except urllib.error.HTTPError as e:
                if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                    url = urllib.parse.urljoin(url, e.headers["Location"])
                    break
                if e.code == 300:
                    return 300, e.headers.get("Content-Type", ""), e.read()
                if e.code in (404, 406, 410):
                    return e.code, "", b""
                if n == tentativas - 1:
                    return e.code, "", b""
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if n == tentativas - 1:
                    raise RuntimeError(f"falha de rede em {url}: {e}") from e
            time.sleep(2 ** (n + 1))
        else:
            continue
    raise RuntimeError(f"demasiados redirecionamentos: {url}")


def sparql(consulta, timeout=600):
    dados = urllib.parse.urlencode(
        {"query": consulta, "format": "application/sparql-results+json"}).encode()
    for n in range(4):
        _esperar("cellar")
        try:
            req = urllib.request.Request(SPARQL, data=dados, headers={
                "User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/sparql-results+json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                res = json.load(resp)
            return [{k: v["value"] for k, v in b.items()} for b in res["results"]["bindings"]]
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            if n == 3:
                raise RuntimeError(f"SPARQL falhou: {e}") from e
            time.sleep(2 ** (n + 2))


PREFIXOS = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""


def _lit(celex):
    return '"%s"^^xsd:string' % celex.replace('"', "")


def codigo_repertorio(uri):
    """.../dir-eu-legal-act/133016 -> 13.30.16"""
    num = uri.rsplit("/", 1)[-1]
    return ".".join(num[i:i + 2] for i in range(0, len(num), 2))


def metadados(celex, lingua="pt"):
    lg3 = LINGUA[lingua][2]
    linhas = sparql(PREFIXOS + f"""
SELECT ?w ?date ?inforce ?eif ?eov ?eli ?title ?dc ?dclabel WHERE {{
  ?w cdm:resource_legal_id_celex {_lit(celex)} .
  OPTIONAL {{ ?w cdm:work_date_document ?date }}
  OPTIONAL {{ ?w cdm:resource_legal_in-force ?inforce }}
  OPTIONAL {{ ?w cdm:resource_legal_date_entry-into-force ?eif }}
  OPTIONAL {{ ?w cdm:resource_legal_date_end-of-validity ?eov }}
  OPTIONAL {{ ?w cdm:resource_legal_eli ?eli }}
  OPTIONAL {{ ?e cdm:expression_belongs_to_work ?w ;
               cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/{lg3}> ;
               cdm:expression_title ?title }}
  OPTIONAL {{ ?w cdm:resource_legal_is_about_concept_directory-code ?dc .
             OPTIONAL {{ ?dc skos:prefLabel ?dclabel FILTER(lang(?dclabel) = "{lingua}") }} }}
}}""")
    if not linhas:
        return None
    m = {"celex": celex, "data_documento": None, "em_vigor": None, "entrada_em_vigor": set(),
         "fim_de_vigencia": set(), "eli": None, "titulo": None, "repertorio": {}}
    for l in linhas:
        m["data_documento"] = m["data_documento"] or l.get("date")
        if "inforce" in l:
            m["em_vigor"] = l["inforce"] in ("true", "1")
        if "eif" in l:
            m["entrada_em_vigor"].add(l["eif"])
        if "eov" in l:
            m["fim_de_vigencia"].add(l["eov"])
        m["eli"] = m["eli"] or l.get("eli")
        m["titulo"] = m["titulo"] or l.get("title")
        if "dc" in l:
            m["repertorio"][codigo_repertorio(l["dc"])] = l.get("dclabel", "")
    m["entrada_em_vigor"] = sorted(m["entrada_em_vigor"])
    m["fim_de_vigencia"] = sorted(m["fim_de_vigencia"])
    if m["titulo"]:
        m["titulo"] = limpar_titulo(m["titulo"])
    return m


def limpar_titulo(t):
    t = t.replace("#", " — ")
    t = re.sub(r"\b([nN])\.\s*[o°º]\s*", r"\1.º ", t)
    t = re.sub(r"(\d)\.\s*[o°]\b", r"\1.º", t)
    t = re.sub(r"\s+([,.;)])", r"\1", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def versoes_consolidadas(celex):
    linhas = sparql(PREFIXOS + f"""
SELECT DISTINCT ?cc ?d WHERE {{
  ?base cdm:resource_legal_id_celex {_lit(celex)} .
  ?c cdm:act_consolidated_based_on_resource_legal ?base ;
     cdm:act_consolidated_date ?d ;
     cdm:resource_legal_id_celex ?cc .
}} ORDER BY DESC(?d)""")
    return [(l["cc"], l["d"][:10]) for l in linhas]


def versoes_consolidadas_todas():
    """[acto de base, versão consolidada, data] de todas as versões consolidadas do Cellar, em
    linhas, uma consulta por ano (de uma só vez o servidor falha). Sem MIN/MAX: nas consultas que
    agrupam vários actos, o SPARQL do Cellar devolve nesses agregados datas de outros actos (ex.:
    TFUE "consolidado até 2026-07-28", quando a versão mais recente é de 2025-03-15). Fica em
    .cache/ durante o dia, para o catálogo e completo.py não repetirem as consultas."""
    cache = RAIZ / ".cache" / "versoes-consolidadas.json"
    hoje = dt.date.today().isoformat()
    if cache.exists():
        guardado = json.loads(cache.read_text(encoding="utf-8"))
        if guardado.get("data") == hoje:
            return guardado["linhas"]
    linhas = []
    for ano in range(1950, dt.date.today().year + 6):
        for l in sparql(PREFIXOS + f"""
SELECT ?base ?cc ?d WHERE {{
  ?c cdm:act_consolidated_based_on_resource_legal ?w ; cdm:act_consolidated_date ?d ; cdm:resource_legal_id_celex ?cc .
  ?w cdm:resource_legal_id_celex ?base .
  FILTER(?d >= "{ano}-01-01"^^xsd:date && ?d < "{ano + 1}-01-01"^^xsd:date)
}}"""):
            linhas.append([l["base"], l["cc"], l["d"][:10]])
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps({"data": hoje, "linhas": linhas}), encoding="utf-8")
    return linhas


def actos_consolidados(cc):
    """CELEX dos actos que uma versão consolidada integra (o acto de base, alterações, rectificações)."""
    linhas = sparql(PREFIXOS + f"""
SELECT DISTINCT ?rc WHERE {{
  ?c cdm:resource_legal_id_celex {_lit(cc)} ;
     cdm:act_consolidated_consolidates_resource_legal ?r .
  ?r cdm:resource_legal_id_celex ?rc .
}}""")
    return sorted(l["rc"] for l in linhas)


def transposicao(celex, pais="PRT"):
    """Medidas nacionais de transposição comunicadas à Comissão (só faz sentido para diretivas)."""
    linhas = sparql(PREFIXOS + f"""
SELECT DISTINCT ?mc ?d (SAMPLE(?t) AS ?title) WHERE {{
  ?base cdm:resource_legal_id_celex {_lit(celex)} .
  ?m cdm:measure_national_implementing_implements_resource_legal ?base ; cdm:resource_legal_id_celex ?mc .
  FILTER(CONTAINS(STR(?mc), "{pais}_"))
  OPTIONAL {{ ?m cdm:work_date_document ?d }}
  OPTIONAL {{ ?e cdm:expression_belongs_to_work ?m ; cdm:expression_title ?t }}
}} GROUP BY ?mc ?d ORDER BY DESC(?d)""")
    return [{"celex": l["mc"], "data": l.get("d", "")[:10],
             "titulo": re.sub(r"\s+", " ", (l.get("title") or "").replace("•", "")).strip()} for l in linhas]


def jurisprudencia(celex, lingua="pt"):
    """Acórdãos e outras decisões do TJUE marcados como interpretando o acto."""
    lg3 = LINGUA[lingua][2]
    linhas = sparql(PREFIXOS + f"""
SELECT ?cc ?ecli ?d (SAMPLE(?t) AS ?title) WHERE {{
  ?base cdm:resource_legal_id_celex {_lit(celex)} .
  ?c cdm:case-law_interpretes_resource_legal ?base ; cdm:resource_legal_id_celex ?cc .
  OPTIONAL {{ ?c cdm:case-law_ecli ?ecli }}
  OPTIONAL {{ ?c cdm:work_date_document ?d }}
  OPTIONAL {{ ?e cdm:expression_belongs_to_work ?c ;
               cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/{lg3}> ;
               cdm:expression_title ?t }}
}} GROUP BY ?cc ?ecli ?d ORDER BY DESC(?d)""")
    return [{"celex": l["cc"], "ecli": l.get("ecli", ""), "data": l.get("d", "")[:10],
             "titulo": limpar_titulo(l.get("title") or "")} for l in linhas]


def sinteses(celex, lingua="pt"):
    """Sínteses oficiais da legislação (\"Sínteses da legislação da UE\", linguagem simples)."""
    lg3 = LINGUA[lingua][2]
    linhas = sparql(PREFIXOS + f"""
SELECT DISTINCT ?id ?t ?obs ?item ?mt WHERE {{
  ?base cdm:resource_legal_id_celex {_lit(celex)} .
  ?s cdm:summary_legislation_eu_summarizes_resource_legal ?base ;
     cdm:summary_legislation_eu_id_legissum ?id .
  OPTIONAL {{ ?s cdm:summary_legislation_eu_obsolete ?obs }}
  ?e cdm:expression_belongs_to_work ?s ;
     cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/{lg3}> .
  OPTIONAL {{ ?e cdm:expression_title ?t }}
  ?m cdm:manifestation_manifests_expression ?e ; cdm:manifestation_type ?mt .
  ?item cdm:item_belongs_to_manifestation ?m .
  FILTER(STRSTARTS(STR(?mt), "xhtml") || STR(?mt) = "html")
}}""")
    res = {}
    for l in linhas:
        if l.get("obs") in ("1", "true"):
            continue
        r = res.setdefault(l["id"], {"id": l["id"], "titulo": l.get("t", ""), "itens": []})
        r["itens"].append((l["mt"], l["item"]))
    return list(res.values())


def guardar_sintese(s, lingua="pt", hoje=None):
    """Grava a síntese em corpus/_sinteses/<id>.md (partilhada entre actos) e devolve o caminho."""
    pasta = CORPUS / "_sinteses"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"{s['id']}.md"
    if destino.exists() and ler_frontmatter(destino).get("obtido_em") == (hoje or dt.date.today().isoformat()):
        return destino
    for _, item in sorted(s["itens"], key=lambda x: x[0] != "xhtml5"):
        estado, _, corpo = http_get(item, {"Accept": "*/*"})
        if estado == 200 and corpo:
            sopa = BeautifulSoup(corpo.decode("utf-8", errors="replace"), "lxml")
            for lixo in sopa.select("header, footer, nav, script, style"):
                lixo.extract()
            alvo = sopa.find("main") or sopa.body or sopa
            md = para_markdown([alvo])
            fm = {"legissum": s["id"], "titulo": s["titulo"], "tipo": "síntese oficial da legislação da UE",
                  "nota": "Resumo em linguagem simples elaborado pelo Serviço das Publicações; não é texto legal.",
                  "url_eurlex": f"https://eur-lex.europa.eu/legal-content/{LINGUA[lingua][0]}/TXT/?uri=LEGISSUM:{s['id']}",
                  "obtido_em": hoje or dt.date.today().isoformat()}
            destino.write_text(_frontmatter(fm) + f"# Síntese: {s['titulo']}\n\n" + md.strip() + "\n",
                               encoding="utf-8")
            return destino
    return None


# ---------------------------------------------------------------------------
# Obtenção do texto
# ---------------------------------------------------------------------------

def _documentos_300(corpo):
    """O Cellar responde 300 quando a manifestação tem vários ficheiros (DOC_1, DOC_2...)."""
    sopa = BeautifulSoup(corpo, "lxml")
    ligs = []
    for a in sopa.find_all("a", href=True):
        h = a["href"]
        if re.search(r"/DOC_\d+$", h) and h not in ligs:
            ligs.append(h)
    return sorted(ligs, key=lambda h: int(h.rsplit("_", 1)[1]))


CACHE = RAIZ / ".cache"


def obter_html(celex, lingua="pt"):
    """Como _obter_html, mas guarda o resultado em .cache/ (fora do git) para que uma nova
    conversão não obrigue a descarregar outra vez. Apagar .cache/ para forçar nova descarga."""
    base = CACHE / "html" / f"{urllib.parse.quote(celex, safe='')}.{lingua}"
    html_f, origem_f = base.with_suffix(base.suffix + ".html"), base.with_suffix(base.suffix + ".origem")
    if html_f.exists() and origem_f.exists():
        return html_f.read_text(encoding="utf-8"), origem_f.read_text(encoding="utf-8").strip()
    html, origem = _obter_html(celex, lingua)
    if html:
        html_f.parent.mkdir(parents=True, exist_ok=True)
        html_f.write_text(html, encoding="utf-8")
        origem_f.write_text(origem, encoding="utf-8")
    return html, origem


def _obter_html(celex, lingua="pt"):
    """Devolve (html, origem). Tenta Cellar XHTML, Cellar HTML e, por fim, o site EUR-Lex."""
    lg2, lg3, _ = LINGUA[lingua]
    url = CELLAR + urllib.parse.quote(celex, safe="")
    for aceitar in ("application/xhtml+xml", "text/html"):
        estado, ctype, corpo = http_get(url, {"Accept": aceitar, "Accept-Language": lg3})
        if estado == 200 and corpo:
            return corpo.decode("utf-8", errors="replace"), f"cellar:{aceitar}"
        if estado == 300:
            partes = []
            for doc in _documentos_300(corpo):
                e2, _, c2 = http_get(urllib.parse.urljoin(url, doc), {"Accept": aceitar})
                if e2 == 200:
                    partes.append(c2.decode("utf-8", errors="replace"))
            if partes:
                return "\n".join(partes), f"cellar:{aceitar} ({len(partes)} ficheiros)"
    estado, _, corpo = http_get(EURLEX.format(lg=lg2, fmt="HTML", celex=urllib.parse.quote(celex, safe="")),
                                {"Accept": "text/html"}, origem="eurlex")
    if estado == 200 and corpo:
        html = corpo.decode("utf-8", errors="replace")
        if re.search(r'id="TexteOnly"|class="eli-container"|id="document1"', html):
            return html, "eur-lex.europa.eu"
    return None, None


# ---------------------------------------------------------------------------
# Conversão HTML -> Markdown
# ---------------------------------------------------------------------------

class Bloco:
    __slots__ = ("tipo", "texto", "nivel", "filhos", "linhas")

    def __init__(self, tipo, texto="", nivel=0, filhos=None, linhas=None):
        self.tipo, self.texto, self.nivel = tipo, texto, nivel
        self.filhos, self.linhas = filhos or [], linhas or []


TAGS_BLOCO = {"p", "div", "table", "tbody", "thead", "tfoot", "tr", "td", "th", "ul", "ol", "li",
              "h1", "h2", "h3", "h4", "h5", "h6", "hr", "dl", "dt", "dd", "blockquote", "center",
              "body", "html", "section", "article", "colgroup", "col", "caption", "form", "txt_te",
              "header", "main", "footer", "nav", "aside"}
IGNORAR = {"script", "style", "head", "col", "colgroup", "hr", "meta", "link", "title", "noscript", "button"}

CL_ARTIGO = {"oj-ti-art", "title-article-norm", "ti-art"}
CL_ARTIGO_SUB = {"oj-sti-art", "stitle-article-norm", "sti-art"}
CL_DIVISAO = {"oj-ti-section-1", "title-division-1", "ti-section-1"}
CL_DIVISAO_SUB = {"oj-ti-section-2", "title-division-2", "ti-section-2"}
CL_ANEXO = {"title-annex-1"}
CL_ANEXO_SUB = {"title-annex-2"}
CL_GRSEQ1 = {"oj-ti-grseq-1", "title-gr-seq-level-1", "ti-grseq-1"}
CL_GRSEQ2 = {"title-gr-seq-level-2", "title-gr-seq-level-3", "title-gr-seq-level-4",
             "oj-ti-grseq-2", "ti-grseq-2"}
CL_NOTA = {"oj-note", "footnote", "note"}
CL_MARCADOR = {"arrow", "modref"}
CL_TITULO_TAB = {"oj-ti-tbl", "title-table", "ti-tbl"}
CL_SUP = {"oj-super", "superscript", "super"}
CL_SUB = {"oj-sub", "subscript", "sub"}

RE_ROTULO = re.compile(r"^(\(?[0-9ivxlcdmA-Za-z]{1,6}[.)]?\)?|[—–\-•▪·]|\(?\d+[.\d]*\)?\.?)$")


def _classes(no):
    return set(no.get("class") or [])


def _limpa(t):
    t = t.replace("\xa0", " ")
    return re.sub(r"[ \t\r\n\f\v]+", " ", t).strip()


def inline(no):
    if isinstance(no, Comment):
        return ""
    if isinstance(no, NavigableString):
        return str(no)
    if not isinstance(no, Tag) or no.name in IGNORAR:
        return ""
    cl = _classes(no)
    if no.name == "br":
        return " "
    if no.name == "img":
        alt = _limpa(no.get("alt", ""))
        return f"[imagem{': ' + alt if alt else ''}]"
    if no.name == "a":
        dentro = _limpa("".join(inline(f) for f in no.children))
        href = no.get("href", "")
        m = re.fullmatch(r"\(?\^?(\*?\d{1,3})\)?", dentro)
        if href.startswith("#") and m:
            return f"[^{m.group(1).strip('*') or '*'}]"
        return dentro
    if no.name == "sup" or cl & CL_SUP:
        t = _limpa("".join(inline(f) for f in no.children))
        if t in ("o", "a", "os", "as"):
            return {"o": "º", "a": "ª"}[t[0]] + t[1:]
        if not t or t.startswith("[^"):
            return t
        return "^" + t
    return "".join(inline(f) for f in no.children)


def _tem_bloco(no):
    return any(isinstance(f, Tag) and f.name in TAGS_BLOCO for f in no.children)


def _texto_plano(no):
    return _limpa(inline(no))


def _normalizar_artigo(t):
    """'Artigo 11.' / 'Artigo 11.o' / 'Artigo 11' -> 'Artigo 11.º' (o Cellar nem sempre põe o expoente)."""
    return re.sub(r"^(Artigo\s+\d+)\s*\.?\s*[oº°]?(?=\s|$|-|\.)", r"\1.º", t)


def _cabecalho(no, nivel):
    t = _texto_plano(no)
    return [Bloco("cab", _normalizar_artigo(t) if nivel == 3 else t, nivel)]


def blocos(no):
    """Converte um nó HTML numa lista de Blocos."""
    if not isinstance(no, Tag) or no.name in IGNORAR:
        return []
    cl = _classes(no)
    if "eli-main-title" in cl:
        return []
    if cl & CL_ARTIGO:
        return _cabecalho(no, 3)
    if cl & CL_ARTIGO_SUB:
        return [Bloco("sub", _texto_plano(no))]
    if cl & CL_DIVISAO or cl & CL_ANEXO:
        return _cabecalho(no, 2)
    if cl & CL_DIVISAO_SUB or cl & CL_ANEXO_SUB:
        return [Bloco("sub", _texto_plano(no))]
    if "oj-doc-ti" in cl or "doc-ti" in cl:
        t = _texto_plano(no)
        if re.match(r"^(ANEXO|APÊNDICE|ANNEX|APPENDIX)\b", t, re.I):
            return [Bloco("cab", t, 2)]
        return [Bloco("sub", t)]
    if cl & CL_GRSEQ1:
        return _cabecalho(no, 4)
    if cl & CL_GRSEQ2:
        return _cabecalho(no, 5)
    if cl & CL_TITULO_TAB:
        t = _texto_plano(no)
        return [Bloco("par", f"**{t}**")] if t else []
    if cl & CL_NOTA:
        t = _texto_plano(no)
        t = re.sub(r"^\(?\[\^(\w+)\]\)?\s*", r"[^\1]: ", t)
        return [Bloco("nota", t)] if t else []
    if cl & CL_MARCADOR:
        t = _texto_plano(no)
        return [Bloco("marca", t)] if t else []
    if no.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        return _cabecalho(no, min(int(no.name[1]) + 1, 5))
    if "grid-list" in cl:
        rot = no.find(class_="grid-list-column-1", recursive=False)
        cont = no.find(class_="grid-list-column-2", recursive=False)
        if rot is not None and cont is not None:
            return [Bloco("item", _texto_plano(rot), filhos=blocos(cont))]
    if no.name == "table":
        return _tabela(no)
    if no.name in ("ul", "ol"):
        res = []
        for i, li in enumerate(no.find_all("li", recursive=False), 1):
            rot = f"{i}." if no.name == "ol" else ""
            res.append(Bloco("item", rot, filhos=_conteudo(li)))
        return res
    return _conteudo(no)


def _conteudo(no):
    """Contentor genérico: junta texto inline em parágrafos e processa os filhos de bloco."""
    res, buf = [], []

    def despejar():
        t = _limpa("".join(buf))
        buf.clear()
        if t:
            res.append(Bloco("par", t))

    if not _tem_bloco(no):
        t = _texto_plano(no)
        return [Bloco("par", t)] if t else []
    for f in no.children:
        if isinstance(f, Tag) and f.name in TAGS_BLOCO:
            despejar()
            res.extend(blocos(f))
        else:
            buf.append(inline(f))
    despejar()
    return _juntar_rotulos(res)


def _juntar_rotulos(bl):
    """'1.' seguido de parágrafo -> '1. texto' (padrão no-parag dos textos consolidados)."""
    out = []
    i = 0
    while i < len(bl):
        b = bl[i]
        if (b.tipo == "par" and len(b.texto) <= 8 and RE_ROTULO.match(b.texto)
                and i + 1 < len(bl) and bl[i + 1].tipo == "par"):
            out.append(Bloco("par", f"{b.texto} {bl[i + 1].texto}"))
            i += 2
            continue
        out.append(b)
        i += 1
    return out


def _linhas_tabela(tab):
    linhas = []
    for parte in [tab] + tab.find_all(["thead", "tbody", "tfoot"], recursive=False):
        for tr in parte.find_all("tr", recursive=False):
            linhas.append(tr.find_all(["td", "th"], recursive=False))
    return linhas


def _tabela(tab):
    linhas = _linhas_tabela(tab)
    if not linhas:
        return _conteudo(tab)
    # Tabela de paginação usada como lista: 2 colunas, a 1.ª é um rótulo curto ("a)", "(3)", "—").
    eh_lista = all(len(c) == 2 for c in linhas) and all(
        len(_texto_plano(c[0])) <= 10 and RE_ROTULO.match(_texto_plano(c[0]) or "x") for c in linhas)
    if eh_lista:
        return [Bloco("item", _texto_plano(c[0]), filhos=blocos_td(c[1])) for c in linhas]
    # Tabela de uma só célula: é só um contentor.
    if len(linhas) == 1 and len(linhas[0]) == 1:
        return blocos_td(linhas[0][0])
    grelha = _grelha(linhas)
    if not any(any(x for x in f) for f in grelha):
        return []
    return [Bloco("tab", linhas=grelha)]


def _inteiro(v):
    try:
        return max(1, int(str(v).strip() or 1))
    except ValueError:
        return 1


def _grelha(linhas):
    """Converte as linhas HTML numa grelha rectangular, respeitando colspan e rowspan.
    Uma célula que ocupa várias linhas (rowspan) é repetida nas linhas seguintes se for curta,
    ou substituída por "(idem)" se for longa, para cada linha se ler sozinha."""
    pend = {}  # coluna -> [linhas que ainda ocupa, texto]
    grelha = []
    # Largura da tabela: a maior soma de colspans de uma linha do HTML.
    largura = max((sum(_inteiro(td.get("colspan", 1)) for td in cells) for cells in linhas), default=1)
    for cells in linhas:
        fila, col, k = [], 0, 0
        while True:
            if pend.get(col, [0])[0] > 0:
                restante, txt = pend[col]
                fila.append(txt if len(txt) <= 120 else ("(idem)" if txt else ""))
                pend[col][0] -= 1
                col += 1
                continue
            if k >= len(cells):
                if any(v[0] > 0 for c, v in pend.items() if c > col):
                    fila.append("")
                    col += 1
                    continue
                break
            td = cells[k]
            k += 1
            txt = " <br> ".join(_achatar(blocos_td(td))).replace("|", "\\|")
            cs, rs = _inteiro(td.get("colspan", 1)), _inteiro(td.get("rowspan", 1))
            # Uma célula larga (ex.: marca ▼M1 em toda a linha) não pode invadir colunas ainda
            # ocupadas por um rowspan de cima; encurta-se até à próxima coluna ocupada.
            seguinte = min((c for c, v in pend.items() if v[0] > 0 and c > col), default=None)
            if seguinte is not None:
                cs = max(1, min(cs, seguinte - col))
            cs = max(1, min(cs, largura - col))  # nem ultrapassar a largura da tabela
            for j in range(cs):
                fila.append(txt if j == 0 else "")
                if rs > 1:
                    pend[col + j] = [rs - 1, txt if j == 0 else ""]
            col += cs
        grelha.append(fila)
    return grelha


def blocos_td(td):
    return _conteudo(td)


def _achatar(bl):
    out = []
    for b in bl:
        if b.tipo == "item":
            out.append(_limpa(f"{b.texto} " + " ".join(_achatar(b.filhos))))
        elif b.tipo == "tab":
            for f in b.linhas:
                out.append(" ; ".join(x for x in f if x))
        elif b.texto:
            out.append(b.texto)
    return out


def _fundir_cabecalhos(bl):
    out = []
    for b in bl:
        if b.tipo == "sub" and out and out[-1].tipo == "cab" and "—" not in out[-1].texto and b.texto:
            out[-1].texto = f"{out[-1].texto} — {b.texto}"
            continue
        if b.tipo == "sub":
            b = Bloco("par", f"**{b.texto}**") if b.texto else None
        if b is not None:
            if b.filhos:
                b.filhos = _fundir_cabecalhos(b.filhos)
            out.append(b)
    return out


def serializar(bl, nivel=0):
    pedacos = []
    ind = "  " * nivel
    for b in bl:
        if b.tipo == "cab":
            if b.texto:
                pedacos.append("#" * b.nivel + " " + b.texto)
        elif b.tipo in ("par", "nota", "marca"):
            if b.texto:
                pedacos.append(ind + b.texto)
        elif b.tipo == "item":
            filhos = b.filhos
            primeiro = ""
            if filhos and filhos[0].tipo == "par":
                primeiro, filhos = filhos[0].texto, filhos[1:]
            cab = _limpa(f"{b.texto} {primeiro}")
            pedacos.append(f"{ind}- {cab}" if cab else f"{ind}-")
            resto = serializar(filhos, nivel + 1)
            if resto:
                pedacos.append(resto)
        elif b.tipo == "tab":
            n = max(len(f) for f in b.linhas)
            fil = [f + [""] * (n - len(f)) for f in b.linhas]
            ls = [ind + "| " + " | ".join(fil[0]) + " |", ind + "|" + "---|" * n]
            ls += [ind + "| " + " | ".join(f) + " |" for f in fil[1:]]
            pedacos.append("\n".join(ls))
    return "\n\n".join(p for p in pedacos if p.strip())


def para_markdown(nos):
    bl = []
    for no in nos:
        bl.extend(blocos(no))
    return serializar(_fundir_cabecalhos(bl))


def analisar(html):
    """Separa um documento em: alterações (consolidados), preâmbulo e parte dispositiva."""
    sopa = BeautifulSoup(html, "lxml")
    for c in sopa.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    corpo = sopa.body or sopa
    alteracoes = []
    for p in corpo.find_all("p", class_="arrow"):
        if p.find_parent(class_="eli-container"):
            continue
        rot = _texto_plano(p)
        tr = p.find_parent("tr")
        if not tr or not re.match(r"^►[A-Z]\d+", rot):
            continue
        celulas = [_texto_plano(td) for td in tr.find_all("td", recursive=False)]
        a = p.find("a")
        alteracoes.append({"marca": rot, "celex": (a.get("title", "").split(":")[0] if a else ""),
                           "descricao": " — ".join(x for x in celulas[1:] if x)})
    contentores = corpo.find_all("div", class_="eli-container")
    preambulo, dispositivo = [], []
    if contentores:
        for cont in contentores:
            for f in cont.children:
                if not isinstance(f, Tag):
                    continue
                if f.get("id", "").startswith("pbl_"):
                    preambulo.append(f)
                else:
                    dispositivo.append(f)
        # notas de rodapé e partes que ficam fora do eli-container
        for f in contentores[-1].find_next_siblings():
            if isinstance(f, Tag):
                dispositivo.append(f)
    else:
        # Documentos antigos sem marcação ELI: o texto todo vai para a parte dispositiva.
        alvo = corpo.find(id="TexteOnly") or corpo.find(id="text") or corpo.find(id="document1") or corpo
        if alvo is corpo:
            for lixo in corpo.select("p.reference, p.disclaimer"):
                lixo.extract()
            # cabeçalho dos consolidados antigos (tabela de alterações)
            for t in corpo.find_all("table"):
                if t.find("p", class_="arrow") and t.find_parent(class_="eli-container") is None \
                        and t.find(class_=re.compile("title-doc|title-fam")):
                    t.extract()
            for p in corpo.find_all("p", class_=re.compile("hd-modifiers|hd-correctors")):
                p.extract()
        if alvo is not corpo:
            pre_md, disp_md = _analisar_antigo(alvo)
            return {"alteracoes": alteracoes, "preambulo": pre_md, "dispositivo": disp_md}
        dispositivo = [alvo]
    return {"alteracoes": alteracoes,
            "preambulo": para_markdown(preambulo) if preambulo else "",
            "dispositivo": para_markdown(dispositivo)}


RE_ADOPCAO = re.compile(r"^(ADOPTARAM|ADOTARAM|ADOPTOU|ADOTOU|APROVARAM|APROVOU|DECIDIU|DECIDIRAM|DECIDE|"
                        r"ADOPTA|ADOTA|ADOPTED|HAVE ADOPTED|HAS ADOPTED|HAS DECIDED)\b.*:?$")
RE_INICIO_PREAMBULO = re.compile(r"^(O PARLAMENTO EUROPEU|O CONSELHO|A COMISSÃO|THE EUROPEAN PARLIAMENT|"
                                 r"THE COUNCIL|THE EUROPEAN COMMISSION|THE COMMISSION)")
RE_ARTIGO = re.compile(r"^(Artigo|Article)\s+\d+\s*\.?\s*[oº°]?(\s*-?\s*[A-Z])?\.?$")
RE_DIVISAO = re.compile(r"^(PARTE|TÍTULO|CAPÍTULO|SECÇÃO|SUBSECÇÃO|Secção|Subsecção|PART|TITLE|CHAPTER|SECTION)"
                        r"\s+([IVXLC]+|\d+|[A-Z]|PRIMEIR[AO]|ÚNIC[AO])\b")
RE_ANEXO = re.compile(r"^(ANEXO|APÊNDICE|ANNEX|APPENDIX)(\s+[IVXLC\d]+[A-Z]?)?$")


def _ordinais_texto(t):
    """Documentos antigos trazem '95.o' e 'n.o' em texto simples em vez de expoente."""
    t = re.sub(r"(\d)\.\s?o\b", r"\1.º", t)
    t = re.sub(r"\b([nN])\.\s?(o|os)\b", lambda m: f"{m.group(1)}.º{'s' if m.group(2) == 'os' else ''}", t)
    return t


def _analisar_antigo(alvo):
    """Texto do JO anterior à marcação ELI: uma sequência de parágrafos sem classes.
    Separa o preâmbulo pela fórmula de adopção ("ADOPTARAM A PRESENTE DIRECTIVA:") e
    reconhece artigos, divisões e anexos pelo texto."""
    bl = []
    for no in (alvo if isinstance(alvo, list) else [alvo]):
        bl.extend(blocos(no))
    for b in bl:
        if b.tipo == "par":
            b.texto = _ordinais_texto(b.texto)
    corte = next((i for i, b in enumerate(bl) if b.tipo == "par" and RE_ADOPCAO.match(b.texto)), None)
    if corte is None:
        pre, disp = [], bl
    else:
        inicio = next((i for i, b in enumerate(bl[:corte]) if b.tipo == "par"
                       and RE_INICIO_PREAMBULO.match(b.texto)), 0)
        pre, disp = bl[inicio:corte + 1], bl[corte + 1:]
    out = []
    i = 0
    while i < len(disp):
        b = disp[i]
        if b.tipo == "par":
            t = b.texto
            nivel = 3 if RE_ARTIGO.match(t) else 2 if (RE_DIVISAO.match(t) and len(t) < 40) or RE_ANEXO.match(t) else 0
            if nivel:
                t = re.sub(r"^(Artigo|Article)\s+(\d+)\s*\.?\s*[oº°]?", lambda m: f"{m.group(1)} {m.group(2)}.º"
                           if m.group(1) == "Artigo" else f"{m.group(1)} {m.group(2)}", t)
                cab = Bloco("cab", t, nivel)
                seg = disp[i + 1] if i + 1 < len(disp) else None
                if (seg is not None and seg.tipo == "par" and len(seg.texto) < 160
                        and not re.search(r"[.;:,]$", seg.texto) and not RE_ARTIGO.match(seg.texto)
                        and not RE_DIVISAO.match(seg.texto) and not re.match(r"^\(?\d+[.)]", seg.texto)):
                    cab.texto += f" — {seg.texto}"
                    i += 1
                out.append(cab)
                i += 1
                continue
        out.append(b)
        i += 1
    return serializar(pre), serializar(out)


# ---------------------------------------------------------------------------
# Escrita no corpus
# ---------------------------------------------------------------------------

def url_eurlex(celex, lingua="pt"):
    return f"https://eur-lex.europa.eu/legal-content/{LINGUA[lingua][0]}/TXT/?uri=CELEX:{urllib.parse.quote(celex, safe='')}"


def nome_tipo(celex):
    m = re.match(r"^([0-9CE])(\d{4})([A-Z])", celex)
    if not m:
        return "Acto"
    if m.group(1) in ("3", "0"):
        return TIPOS_3.get(m.group(3), "Outro acto")
    return TIPOS_SECTOR.get(m.group(1), "Acto")


def _escolher_versao(versoes, hoje):
    """Versões consolidadas por ordem decrescente de data; escolhe a mais recente já aplicável."""
    vigentes = [v for v in versoes if v[1] <= hoje]
    futuras = [v for v in versoes if v[1] > hoje]
    return vigentes, futuras


def obter_acto(celex, area, curto=None, lingua="pt", considerandos=True, hoje=None):
    hoje = hoje or dt.date.today().isoformat()
    meta = metadados(celex, lingua)
    if meta is None:
        raise RuntimeError(f"{celex}: não encontrado no Cellar")
    versoes = versoes_consolidadas(celex)
    vigentes, futuras = _escolher_versao(versoes, hoje)

    html, origem, versao = None, None, None
    for cc, d in vigentes:
        html, origem = obter_html(cc, lingua)
        if html:
            versao = (cc, d)
            break
    # Consolidações mais recentes do que a usada, mas sem texto nesta língua no Cellar.
    # Só interessam as que integram alterações (as outras são o texto original ou rectificações).
    sem_texto, rectif = [], set()
    for cc, d in vigentes:
        if versao is not None and d <= versao[1]:
            continue
        integrados = actos_consolidados(cc)
        alteradores = [r for r in integrados if not r.startswith(celex)]
        if alteradores:
            sem_texto.append(f"{cc} ({d}; integra {', '.join(alteradores)})")
        elif versao is None:
            rectif.update(r for r in integrados if r.startswith(celex + "R("))
    if html is None:
        html, origem = obter_html(celex, lingua)
        if html is None:
            raise RuntimeError(f"{celex}: sem texto disponível em {lingua}")
    partes = analisar(html)

    pre = partes["preambulo"] if considerandos else ""
    if considerandos and versao is not None:
        html_orig, _ = obter_html(celex, lingua)
        if html_orig:
            pre = analisar(html_orig)["preambulo"]

    pasta = CORPUS / area
    pasta.mkdir(parents=True, exist_ok=True)
    base = celex.replace("/", "_") + (f"-{slug(curto)}" if curto else "")
    principal = pasta / f"{base}.md"
    ficheiro_pre = pasta / f"{base}.considerandos.md"
    ficheiro_ctx = pasta / f"{base}.contexto.md"
    contexto = gerar_contexto(celex, titulo_curto=f"{nome_tipo(celex)} {celex}" + (f" — {curto}" if curto else ""),
                              lingua=lingua, hoje=hoje, destino=ficheiro_ctx)

    fm = {
        "celex": celex,
        "nome_curto": curto,
        "tipo": nome_tipo(celex),
        "titulo": meta["titulo"],
        "data_documento": meta["data_documento"],
        "em_vigor": meta["em_vigor"],
        "entrada_em_vigor": meta["entrada_em_vigor"] or None,
        # Só quando o acto já não está em vigor: em actos vigentes o Cellar tem às vezes datas
        # de fim de validade que dizem respeito a partes do acto e induziriam em erro.
        "fim_de_vigencia": ([d for d in meta["fim_de_vigencia"] if not d.startswith("9999")] or None)
        if meta["em_vigor"] is False else None,
        "texto": "consolidado" if versao else "original (JO)",
        "versao_consolidada": versao[0] if versao else None,
        "versao_aplicavel_desde": versao[1] if versao else None,
        "versoes_futuras": [f"{c} ({d})" for c, d in futuras] or None,
        "consolidacoes_sem_texto_na_lingua": sem_texto or None,
        "rectificacoes_nao_incorporadas": sorted(rectif) or None,
        "eli": meta["eli"],
        "repertorio": [f"{k} {v}".strip() for k, v in sorted(meta["repertorio"].items())] or None,
        "url_eurlex": url_eurlex(celex, lingua),
        "url_versao": url_eurlex(versao[0], lingua) if versao else None,
        "lingua": lingua,
        "fonte": origem,
        "obtido_em": hoje,
    }
    fm = {k: v for k, v in fm.items() if v not in (None, [], "")}

    titulo_md = f"{nome_tipo(celex)} {celex}" + (f" — {curto}" if curto else "")
    cab = [f"# {titulo_md}", "", f"**Título oficial:** {meta['titulo'] or '(sem título em ' + lingua + ')'}", ""]
    if versao:
        cab += [f"**Texto:** versão consolidada aplicável desde {versao[1]} ({versao[0]}).", "",
                "> Aviso oficial dos textos consolidados: são um instrumento de documentação sem efeito "
                "jurídico. Fazem fé apenas os textos publicados no Jornal Oficial da União Europeia.", ""]
        if futuras:
            cab += [f"**Atenção:** já existem versões consolidadas com data futura: "
                    + ", ".join(f"{c} ({d})" for c, d in futuras) + ". Confirmar no EUR-Lex se a "
                    "pergunta for sobre essas datas.", ""]
    else:
        cab += ["**Texto:** versão original publicada no Jornal Oficial.", ""]
    if sem_texto:
        cab += ["**Atenção:** existem versões consolidadas mais recentes, com alterações, que o Cellar "
                f"não tem em {lingua.upper()}: " + "; ".join(sem_texto) + ". Este ficheiro **não inclui "
                "essas alterações** — ler também os actos alteradores (CELEX indicados) ou confirmar no "
                "EUR-Lex.", ""]
    if rectif:
        cab += [f"**Nota:** há rectificações publicadas no JO que este texto original não incorpora "
                f"({', '.join(sorted(rectif))}). Muitas rectificações dizem respeito só a algumas versões "
                "linguísticas; não foi verificado se alguma altera o texto português. Confirmar no EUR-Lex "
                "antes de citar um passo decisivo.", ""]
    if pre:
        cab += [f"**Considerandos (preâmbulo):** ficheiro `{ficheiro_pre.name}`.", ""]
    if contexto:
        cab += [f"**Contexto** (sínteses oficiais, transposição em Portugal, jurisprudência do TJUE): "
                f"ficheiro `{ficheiro_ctx.name}`.", ""]
    cab += [f"**EUR-Lex:** {fm['url_eurlex']}", ""]
    if partes["alteracoes"]:
        cab += ["## Alterações incorporadas nesta versão", "",
                "No texto, ▼M1/►M1 marcam disposições alteradas pelo acto M1 (e assim por diante), "
                "▼C1 marca rectificações, ▼A1 actos de adesão e ▼B o texto de base.", ""]
        cab += [f"- {a['marca']} {a['descricao']} (CELEX {a['celex']})" for a in partes["alteracoes"]]
        cab += [""]
    cab += ["## Texto", ""]

    principal.write_text(_frontmatter(fm) + "\n".join(cab) + "\n" + partes["dispositivo"].strip() + "\n",
                         encoding="utf-8")
    if pre:
        fm_pre = {"celex": celex, "nome_curto": curto, "parte": "considerandos",
                  "nota": "Preâmbulo do texto original publicado no JO (os consolidados não o incluem).",
                  "url_eurlex": url_eurlex(celex, lingua), "obtido_em": hoje}
        fm_pre = {k: v for k, v in fm_pre.items() if v}
        ficheiro_pre.write_text(_frontmatter(fm_pre) + f"# {titulo_md} — considerandos\n\n"
                                + pre.strip() + "\n", encoding="utf-8")
    elif ficheiro_pre.exists():
        ficheiro_pre.unlink()
    return principal, fm


def gerar_contexto(celex, titulo_curto, lingua, hoje, destino):
    """Ficheiro <acto>.contexto.md: sínteses, transposição em Portugal e jurisprudência."""
    sins = sinteses(celex, lingua)
    trans = transposicao(celex) if re.match(r"^3\d{4}L", celex) else []
    juris = jurisprudencia(celex, lingua)
    if not (sins or trans or juris):
        if destino.exists():
            destino.unlink()
        return False
    ls = [_frontmatter({"celex": celex, "parte": "contexto", "obtido_em": hoje}).rstrip("\n"), "",
          f"# {titulo_curto} — contexto", "",
          "Metadados do Cellar (Serviço das Publicações da UE). As listas são as que o EUR-Lex associa "
          "a este acto; podem estar incompletas ou atrasadas.", ""]
    if sins:
        ls += ["## Sínteses oficiais (linguagem simples)", ""]
        for s_ in sins:
            f = guardar_sintese(s_, lingua, hoje)
            alvo = f"[`_sinteses/{f.name}`](../_sinteses/{f.name})" if f else "(texto indisponível)"
            ls.append(f"- {s_['titulo']} — {alvo}")
        ls.append("")
    if re.match(r"^3\d{4}L", celex):
        ls += ["## Transposição em Portugal", "",
               "Medidas nacionais que Portugal comunicou à Comissão como transpondo esta diretiva "
               "(mais recentes primeiro; fonte: Cellar). Quando foi possível obter o texto no Diário da "
               "República, a linha liga ao ficheiro em `legislacao-pt/` e indica se é a versão consolidada, "
               "o texto original (sem alterações posteriores) ou um diploma revogado.", ""]
        if trans:
            pt = legislacao_pt()
            for t in trans:
                m = pt["por_celex"].get(t["celex"])
                ligacao = ""
                if m and m.get("estado") not in (None, "excluída", "falhou a recolha"):
                    ligacao = f" → texto: [`legislacao-pt/{m['chave']}.md`](../../legislacao-pt/{m['chave']}.md) ({m['estado']})"
                elif m and m.get("excluida"):
                    ligacao = f" → não obtido do DRE: {m['excluida']}"
                ls.append(f"- {t['data']} — {t['titulo']} (CELEX {t['celex']}){ligacao}")
        else:
            ls.append("- Nenhuma medida portuguesa registada no Cellar para esta diretiva.")
        ls.append("")
    relacionados = legislacao_pt()["por_acto"].get(celex, [])
    if relacionados:
        ls += ["## Legislação portuguesa relacionada", "",
               "Diplomas portugueses ligados a este acto por uma fonte citada no próprio ficheiro "
               "(ex.: lei de execução de um regulamento).", ""]
        ls += [f"- [{m.get('titulo') or m['chave']}](../../legislacao-pt/{m['chave']}.md) ({m['estado']})"
               for m in relacionados]
        ls.append("")
    if juris:
        ls += [f"## Jurisprudência do Tribunal de Justiça que interpreta este acto ({len(juris)})", "",
               "Para obter o texto de uma decisão: `python3 ferramentas/eurlex.py obter <CELEX> "
               "--area jurisprudencia`.", ""]
        for j in juris:
            tit = j["titulo"] if len(j["titulo"]) <= 700 else j["titulo"][:697] + "…"
            ls.append(f"- {j['data']} — {j['celex']} {j['ecli']} — {tit}")
        ls.append("")
    destino.write_text("\n".join(ls), encoding="utf-8")
    return True


_LEG_PT = None


def legislacao_pt():
    """Mapa das leis portuguesas obtidas por ferramentas/dre.py (legislacao-pt/medidas.json)."""
    global _LEG_PT
    if _LEG_PT is None:
        f = RAIZ / "legislacao-pt" / "medidas.json"
        dados = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
        por_celex, por_acto = {}, {}
        for m in dados:
            for c in m.get("celex_medidas") or []:
                por_celex[c] = m
            for c in m.get("relacionado_com") or []:
                if m.get("estado") not in ("excluída", "falhou a recolha"):
                    por_acto.setdefault(c, []).append(m)
        _LEG_PT = {"por_celex": por_celex, "por_acto": por_acto}
    return _LEG_PT


def _frontmatter(fm):
    return "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, width=1000) + "---\n\n"


def slug(t):
    import unicodedata
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


# ---------------------------------------------------------------------------
# Índice do corpus
# ---------------------------------------------------------------------------

def ler_frontmatter(caminho):
    txt = caminho.read_text(encoding="utf-8")
    if not txt.startswith("---\n"):
        return {}
    fim = txt.find("\n---\n", 4)
    return yaml.safe_load(txt[4:fim]) or {}


def gerar_indice():
    nucleo = yaml.safe_load(NUCLEO.read_text(encoding="utf-8")) if NUCLEO.exists() else {"areas": {}}
    titulos_area = {k: v.get("titulo", k) for k, v in nucleo.get("areas", {}).items()}
    linhas = ["# Índice do corpus", "",
              "Gerado por `python3 ferramentas/eurlex.py indice`. Uma linha por acto. Ao lado de cada "
              "ficheiro: `.considerandos.md` (preâmbulo) e `.contexto.md` (sínteses, transposição em "
              "Portugal, jurisprudência), quando existem. Sínteses oficiais em `_sinteses/`.", "",
              "Colunas: CELEX · nome curto · texto (consolidado/original) · versão aplicável desde · "
              "em vigor · tamanho.", ""]
    total, n = 0, 0
    ordem = list(titulos_area)
    pastas = [p for p in CORPUS.iterdir() if p.is_dir() and not p.name.startswith("_")]
    for pasta in sorted(pastas, key=lambda p: (ordem.index(p.name) if p.name in ordem else len(ordem), p.name)):
        fich = sorted(f for f in pasta.glob("*.md")
                      if not f.name.endswith((".considerandos.md", ".contexto.md")) and f.name != "README.md")
        if not fich:
            continue
        linhas += [f"## {titulos_area.get(pasta.name, pasta.name)} (`corpus/{pasta.name}/`)", "",
                   "| CELEX | Nome | Texto | Versão desde | Em vigor | KB | Título oficial |",
                   "|---|---|---|---|---|---|---|"]
        for f in fich:
            fm = ler_frontmatter(f)
            kb = f.stat().st_size // 1024
            total += f.stat().st_size
            n += 1
            tit = (fm.get("titulo") or "").replace("|", "/")
            if len(tit) > 220:
                tit = tit[:217] + "…"
            vig = {True: "sim", False: "não"}.get(fm.get("em_vigor"), "?")
            linhas.append(f"| [{fm.get('celex')}]({pasta.name}/{f.name}) | {fm.get('nome_curto') or ''} | "
                          f"{fm.get('texto', '')} | {fm.get('versao_aplicavel_desde') or fm.get('data_documento') or ''} | "
                          f"{vig} | {kb} | {tit} |")
        linhas.append("")
    linhas.insert(4, f"Total: {n} actos, {total // (1024 * 1024)} MB de texto principal "
                     f"(sem contar considerandos).\n")
    (CORPUS / "INDICE.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return n


# ---------------------------------------------------------------------------
# Catálogo de toda a legislação em vigor
# ---------------------------------------------------------------------------

def gerar_catalogo(lingua="pt"):
    """Lista todos os actos com 'em vigor = sim' no Cellar (sectores 1 a 4 do CELEX)."""
    lg3 = LINGUA[lingua][2]
    CATALOGO.mkdir(exist_ok=True)
    actos = {}
    for sector in "1234":
        for ano in range(1951, dt.date.today().year + 1):
            pref = f"{sector}{ano}"
            linhas = sparql(PREFIXOS + f"""
SELECT ?celex ?date ?eli (SAMPLE(?t) AS ?title) (GROUP_CONCAT(DISTINCT ?dc; separator=" ") AS ?dcs) WHERE {{
  ?w cdm:resource_legal_in-force "true"^^xsd:boolean ;
     cdm:resource_legal_id_celex ?celex .
  FILTER(STRSTARTS(STR(?celex), "{pref}"))
  OPTIONAL {{ ?w cdm:work_date_document ?date }}
  OPTIONAL {{ ?w cdm:resource_legal_eli ?eli }}
  OPTIONAL {{ ?e cdm:expression_belongs_to_work ?w ;
               cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/{lg3}> ;
               cdm:expression_title ?t }}
  OPTIONAL {{ ?w cdm:resource_legal_is_about_concept_directory-code ?dc }}
}} GROUP BY ?celex ?date ?eli""")
            for l in linhas:
                c = l["celex"]
                actos[c] = {
                    "celex": c, "data": (l.get("date") or "")[:10],
                    "tipo": nome_tipo(c),
                    "repertorio": " ".join(sorted(codigo_repertorio(x) for x in l.get("dcs", "").split() if x)),
                    "titulo": limpar_titulo(l.get("title") or ""), "eli": l.get("eli", ""),
                }
            if linhas:
                print(f"  {pref}: {len(linhas)}", file=sys.stderr)
    # versão consolidada mais recente de cada acto (máximo calculado aqui, não no Cellar)
    ultima = {}
    for base, _cc, d in versoes_consolidadas_todas():
        if d > ultima.get(base, ""):
            ultima[base] = d

    campos = ["celex", "data", "tipo", "consolidado_ate", "repertorio", "titulo", "eli", "url"]
    with open(CATALOGO / "legislacao-em-vigor.tsv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(campos)
        for c in sorted(actos):
            a = actos[c]
            w.writerow([a["celex"], a["data"], a["tipo"], ultima.get(c, ""), a["repertorio"],
                        a["titulo"].replace("\t", " "), a["eli"], url_eurlex(c, lingua)])
    gerar_repertorio(lingua)
    return len(actos)


def gerar_repertorio(lingua="pt"):
    """catalogo/repertorio.md: árvore de áreas do EUR-Lex com contagem de actos em vigor."""
    rep = sparql(PREFIXOS + f"""
SELECT ?dc ?label WHERE {{
  ?dc skos:inScheme <http://publications.europa.eu/resource/authority/dir-eu-legal-act> ;
      skos:prefLabel ?label . FILTER(lang(?label) = "{lingua}")
}}""")
    rotulos = {}
    for l in rep:
        cod = codigo_repertorio(l["dc"])
        if re.fullmatch(r"\d{2}(\.\d{2})*", cod):
            rotulos[cod] = l["label"]
    contagem = {}
    with open(CATALOGO / "legislacao-em-vigor.tsv", encoding="utf-8", newline="") as fh:
        for linha in csv.DictReader(fh, delimiter="\t"):
            prefixos = set()
            for cod in linha["repertorio"].split():
                for k in range(2, len(cod) + 1, 3):
                    prefixos.add(cod[:k])
            for pre in prefixos:
                contagem[pre] = contagem.get(pre, 0) + 1
    ls = ["# Repertório da legislação da UE em vigor", "",
          "Classificação oficial do EUR-Lex (\"Repertório da legislação em vigor\"), três níveis. "
          "Para cada código, o número de actos de `legislacao-em-vigor.tsv` com esse código ou um "
          "subcódigo (um acto pode estar em várias áreas). Listar os actos de uma área:", "",
          "```bash", "awk -F'\\t' '$5 ~ /(^| )13\\.30\\.16/' catalogo/legislacao-em-vigor.tsv | cut -f1,2,6",
          "```", ""]
    for cod in sorted(rotulos, key=lambda x: [int(p) for p in x.split(".")]):
        prof = cod.count(".")
        if prof > 2:
            continue
        ls.append(f"{'  ' * prof}- `{cod}` {rotulos[cod]} — {contagem.get(cod, 0)} acto{'' if contagem.get(cod, 0) == 1 else 's'}")
    (CATALOGO / "repertorio.md").write_text("\n".join(ls) + "\n", encoding="utf-8")
    return len(rotulos)


# ---------------------------------------------------------------------------
# Linha de comandos
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("obter", help="descarregar actos por CELEX")
    o.add_argument("celex", nargs="+")
    o.add_argument("--area", default="outros")
    o.add_argument("--curto")
    o.add_argument("--lingua", default="pt", choices=sorted(LINGUA))
    o.add_argument("--sem-considerandos", action="store_true")
    n = sub.add_parser("nucleo", help="descarregar a lista curada")
    n.add_argument("--so", nargs="*", help="só estes CELEX")
    n.add_argument("--area", help="só esta área")
    n.add_argument("--lingua", default="pt", choices=sorted(LINGUA))
    c = sub.add_parser("catalogo", help="gerar catálogo da legislação em vigor")
    c.add_argument("--lingua", default="pt", choices=sorted(LINGUA))
    sub.add_parser("indice", help="regenerar corpus/INDICE.md")
    sub.add_parser("repertorio", help="regenerar catalogo/repertorio.md a partir do catálogo")
    a = ap.parse_args()

    if a.cmd == "obter":
        for cx in a.celex:
            f, fm = obter_acto(cx, a.area, a.curto, a.lingua, not a.sem_considerandos)
            print(f"{cx}: {f.relative_to(RAIZ)} ({fm.get('texto')})")
        gerar_indice()
    elif a.cmd == "nucleo":
        dados = yaml.safe_load(NUCLEO.read_text(encoding="utf-8"))
        falhas = []
        for area, info in dados["areas"].items():
            if a.area and area != a.area:
                continue
            for acto in info["actos"]:
                if a.so and acto["celex"] not in a.so:
                    continue
                try:
                    f, fm = obter_acto(acto["celex"], area, acto.get("curto"), a.lingua,
                                       acto.get("considerandos", True))
                    print(f"ok   {acto['celex']:<22} {fm.get('texto'):<14} {f.stat().st_size // 1024:>6} KB  "
                          f"{f.relative_to(RAIZ)}", flush=True)
                except Exception as e:  # noqa: BLE001 — registar e continuar com os restantes
                    falhas.append((acto["celex"], str(e)))
                    print(f"FALHA {acto['celex']}: {e}", flush=True)
        gerar_indice()
        if falhas:
            print(f"\n{len(falhas)} falhas:", *[f"  {c}: {e}" for c, e in falhas], sep="\n")
            sys.exit(1)
    elif a.cmd == "catalogo":
        print(f"{gerar_catalogo(a.lingua)} actos no catálogo")
    elif a.cmd == "repertorio":
        print(f"{gerar_repertorio()} códigos no repertório")
    elif a.cmd == "indice":
        print(f"{gerar_indice()} actos no índice")


if __name__ == "__main__":
    main()
