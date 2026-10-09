#!/usr/bin/env python3
"""Texto integral, em português, de TODA a legislação da UE em vigor (e da já publicada que
entra em vigor no futuro), em ue/<tipo>/<ano>/<CELEX>.md.

Complementa corpus/ (86 actos curados, com considerandos, sínteses, transposição e
jurisprudência): aqui está tudo, com metadados mais simples.

Comandos:
  listas        lista de trabalho: catálogo em vigor + actos futuros + versões consolidadas
  descarregar   obtém o texto de cada acto da lista (em paralelo; retoma onde parou)
  converter     escreve os ficheiros Markdown e ue/INDICE.tsv
  actualizar    listas + descarregar + converter só do que mudou (usado pela actualização automática)

O texto descarregado fica comprimido em .cache/ue/ (fora do git) para poder reconverter.
"""

import argparse
import concurrent.futures as cf
import csv
import datetime as dt
import gzip
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import eurlex  # noqa: E402

RAIZ = eurlex.RAIZ
SAIDA = RAIZ / "ue"
CACHE = RAIZ / ".cache" / "ue"
LISTA = CACHE / "lista.json"
INDICE = SAIDA / "INDICE.tsv"
CELLAR = "https://publications.europa.eu/resource/celex/"
PAUSA_POR_FIO = 0.5  # segundos entre pedidos de cada fio de execução

PASTAS_3 = {"R": "regulamentos", "L": "diretivas", "D": "decisoes", "H": "recomendacoes",
            "M": "concentracoes", "J": "concentracoes", "A": "pareceres", "B": "orcamento",
            "O": "orientacoes-bce", "E": "pesc", "F": "decisoes-quadro", "G": "resolucoes"}
PASTAS_SECTOR = {"1": "tratados", "2": "acordos-internacionais", "4": "actos-complementares"}


def pasta(celex):
    m = re.match(r"^([0-9])(\d{4})([A-Z])", celex)
    if not m:
        return "outros/sem-ano"
    if m.group(1) == "3":
        p = PASTAS_3.get(m.group(3), "outros")
    else:
        p = PASTAS_SECTOR.get(m.group(1), "outros")
    return f"{p}/{m.group(2)}"


def nome_ficheiro(celex):
    return re.sub(r"[^A-Za-z0-9()_.-]", "_", celex)


# ---------------------------------------------------------------------------
# Rede (segura para vários fios)
# ---------------------------------------------------------------------------

_local = threading.local()


class SemRedirecionar(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_abridor = urllib.request.build_opener(SemRedirecionar)
_bloqueio = threading.Lock()
_pausa_global = {"ate": 0.0}  # quando o servidor pede calma (429/503), todos esperam


def _esperar():
    ultimo = getattr(_local, "ultimo", 0.0)
    falta = max(ultimo + PAUSA_POR_FIO, _pausa_global["ate"]) - time.monotonic()
    if falta > 0:
        time.sleep(falta)
    _local.ultimo = time.monotonic()


def get(url, accept, lingua="por", tentativas=5):
    cab = {"User-Agent": eurlex.UA, "Accept": accept, "Accept-Language": lingua}
    for _ in range(8):  # redirecionamentos
        url = re.sub(r"^http://", "https://", url)
        for n in range(tentativas):
            _esperar()
            try:
                r = _abridor.open(urllib.request.Request(url, headers=cab), timeout=300)
                return r.status, r.headers.get("Content-Type", ""), r.read()
            except urllib.error.HTTPError as e:
                if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                    url = urllib.parse.urljoin(url, e.headers["Location"])
                    break
                if e.code == 300:
                    return 300, e.headers.get("Content-Type", ""), e.read()
                if e.code in (404, 406, 410):
                    return e.code, "", b""
                if e.code in (429, 503):
                    with _bloqueio:
                        _pausa_global["ate"] = max(_pausa_global["ate"], time.monotonic() + 30 * (n + 1))
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                pass
            time.sleep(2 ** (n + 1))
        else:
            return 0, "", b""
    return 0, "", b""


def conteudo(celex, lingua="por"):
    """(texto, formato) do acto na língua pedida: XHTML, HTML ou, em último caso, PDF -> texto."""
    url = CELLAR + urllib.parse.quote(celex, safe="")
    for aceitar, fmt in (("application/xhtml+xml", "html"), ("text/html", "html"), ("application/pdf", "pdf")):
        estado, ctype, corpo = get(url, aceitar, lingua)
        if estado == 300:
            partes = []
            for doc in eurlex._documentos_300(corpo):
                e2, _, c2 = get(urllib.parse.urljoin(url, doc), aceitar, lingua)
                if e2 == 200:
                    partes.append(c2)
            if not partes:
                continue
            if fmt == "pdf":
                return "\n\n".join(pdf_texto(p) for p in partes), "pdf"
            return sem_imagens("\n".join(p.decode("utf-8", "replace") for p in partes)), fmt
        if estado == 200 and corpo:
            if fmt == "pdf":
                return pdf_texto(corpo), "pdf"
            return sem_imagens(corpo.decode("utf-8", "replace")), fmt
    return None, None


RE_IMAGEM_EMBUTIDA = re.compile(r"data:image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+")


def sem_imagens(html):
    """Retira imagens embutidas em base64 (os regulamentos UNECE chegam a 27 MB só disso);
    o Markdown mostra-as como [imagem]."""
    return RE_IMAGEM_EMBUTIDA.sub("data:removida", html)


def pdf_texto(dados):
    with tempfile.TemporaryDirectory() as d:
        f = pathlib.Path(d) / "a.pdf"
        f.write_bytes(dados)
        r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(f), "-"], capture_output=True)
        return r.stdout.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# Listas
# ---------------------------------------------------------------------------

def _paginar(consulta, passo=10000):
    res, desloc = [], 0
    while True:
        linhas = eurlex.sparql(consulta + f"\nLIMIT {passo} OFFSET {desloc}")
        res += linhas
        if len(linhas) < passo:
            return res
        desloc += passo


def cmd_listas():
    hoje = dt.date.today().isoformat()
    actos = {}
    with open(eurlex.CATALOGO / "legislacao-em-vigor.tsv", encoding="utf-8", newline="") as fh:
        for l in csv.DictReader(fh, delimiter="\t"):
            actos[l["celex"]] = {"celex": l["celex"], "titulo": l["titulo"], "data": l["data"], "tipo": l["tipo"],
                                 "repertorio": l["repertorio"], "eli": l["eli"], "estado": "em vigor"}
    # Actos já publicados que só entram em vigor depois de hoje.
    futuros = eurlex.sparql(eurlex.PREFIXOS + f"""
SELECT ?celex (MIN(?eif) AS ?entrada) (SAMPLE(?t) AS ?title) (SAMPLE(?dd) AS ?date) WHERE {{
  ?w cdm:resource_legal_id_celex ?celex ; cdm:resource_legal_date_entry-into-force ?eif .
  FILTER(?eif > "{hoje}"^^xsd:date)
  FILTER(REGEX(STR(?celex), "^[1234]"))
  FILTER NOT EXISTS {{ ?w cdm:resource_legal_in-force "true"^^xsd:boolean }}
  OPTIONAL {{ ?w cdm:work_date_document ?dd }}
  OPTIONAL {{ ?e cdm:expression_belongs_to_work ?w ;
               cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/POR> ;
               cdm:expression_title ?t }}
}} GROUP BY ?celex""")
    for l in futuros:
        c = l["celex"]
        if c not in actos:
            actos[c] = {"celex": c, "titulo": eurlex.limpar_titulo(l.get("title", "")), "data": l.get("date", "")[:10],
                        "tipo": eurlex.nome_tipo(c), "repertorio": "", "eli": "", "estado": "futuro",
                        "entrada_em_vigor": l["entrada"][:10]}
    # Versões consolidadas, por acto de base. Uma consulta por ano (de uma só vez o servidor falha).
    linhas = []
    for ano in range(1950, dt.date.today().year + 6):
        linhas += eurlex.sparql(eurlex.PREFIXOS + f"""
SELECT ?base ?cc ?d WHERE {{
  ?c cdm:act_consolidated_based_on_resource_legal ?w ; cdm:act_consolidated_date ?d ; cdm:resource_legal_id_celex ?cc .
  ?w cdm:resource_legal_id_celex ?base .
  FILTER(?d >= "{ano}-01-01"^^xsd:date && ?d < "{ano + 1}-01-01"^^xsd:date)
}}""")
    for l in linhas:
        a = actos.get(l["base"])
        if a is not None:
            a.setdefault("versoes", []).append([l["cc"], l["d"][:10]])
    for a in actos.values():
        a["versoes"] = sorted({tuple(v) for v in a.get("versoes", [])}, key=lambda v: v[1], reverse=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    LISTA.write_text(json.dumps(actos, ensure_ascii=False), encoding="utf-8")
    n_fut = sum(1 for a in actos.values() if a["estado"] == "futuro")
    n_cons = sum(1 for a in actos.values() if a["versoes"])
    print(f"{len(actos)} actos ({n_fut} futuros); {n_cons} com versões consolidadas; {len(linhas)} versões")
    return actos


# ---------------------------------------------------------------------------
# Descarga
# ---------------------------------------------------------------------------

def _cache(celex):
    return CACHE / "html" / pasta(celex) / f"{nome_ficheiro(celex)}.json.gz"


def plano(a, hoje):
    """Versões a obter: a consolidada mais recente já aplicável (ou o original) e, se houver,
    a versão consolidada futura mais recente."""
    vig = [v for v in a["versoes"] if v[1] <= hoje]
    fut = [v for v in a["versoes"] if v[1] > hoje]
    return vig, (fut[0] if fut else None)


def descarregar_um(a, hoje):
    destino = _cache(a["celex"])
    if destino.exists():
        return "cache"
    vig, fut = plano(a, hoje)
    reg = {"celex": a["celex"], "obtido_em": hoje}
    for cc, d in vig:
        html, fmt = conteudo(cc)
        if html:
            reg.update(texto=html, formato=fmt, versao=cc, versao_data=d)
            break
        reg.setdefault("versoes_sem_pt", []).append([cc, d])
    if "texto" not in reg:
        html, fmt = conteudo(a["celex"])
        if html:
            reg.update(texto=html, formato=fmt, versao=None)
    if "texto" not in reg:
        # Sem versão portuguesa (ex.: decisões sobre concentrações, só na língua do processo).
        for lg in ("eng", "fra", "deu"):
            html, fmt = conteudo(a["celex"], lg)
            if html:
                reg.update(texto=html, formato=fmt, versao=None, lingua=lg)
                break
    if fut:
        html, fmt = conteudo(fut[0])
        if html:
            reg.update(futuro_texto=html, futuro_formato=fmt, futuro_versao=fut[0], futuro_data=fut[1])
    destino.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(destino, "wt", encoding="utf-8") as fh:
        json.dump(reg, fh, ensure_ascii=False)
    return ("ok" if not reg.get("lingua") else f"ok-{reg['lingua']}") if "texto" in reg else "sem texto"


def cmd_descarregar(fios=8, so=None, limite=None):
    actos = json.loads(LISTA.read_text(encoding="utf-8"))
    hoje = dt.date.today().isoformat()
    alvo = [a for a in actos.values() if (not so or a["celex"] in so)]
    alvo.sort(key=lambda a: a["celex"], reverse=True)  # mais recentes primeiro
    if limite:
        alvo = alvo[:limite]
    feitos, estados, inicio = 0, {}, time.time()
    registo = open(CACHE / "descarga.log", "a", encoding="utf-8")
    with cf.ThreadPoolExecutor(max_workers=fios) as ex:
        futs = {ex.submit(descarregar_um, a, hoje): a["celex"] for a in alvo}
        for f in cf.as_completed(futs):
            try:
                e = f.result()
            except Exception as err:  # noqa: BLE001 — registar e continuar
                e = f"erro: {err}"
            estados[e.split(":")[0]] = estados.get(e.split(":")[0], 0) + 1
            registo.write(f"{e}\t{futs[f]}\n")
            feitos += 1
            if feitos % 500 == 0 or feitos == len(alvo):
                registo.flush()
                ritmo = feitos / max(1, time.time() - inicio)
                print(f"{feitos}/{len(alvo)} {estados} {ritmo:.1f}/s", flush=True)
    registo.close()
    return estados


# ---------------------------------------------------------------------------
# Conversão
# ---------------------------------------------------------------------------

def _corpo(texto, formato):
    if formato == "pdf":
        t = re.sub(r"[ \t]+\n", "\n", texto)
        return {"alteracoes": [], "preambulo": "", "dispositivo": "```text\n" + t.strip() + "\n```"}
    return eurlex.analisar(texto)


def converter_um(a, rel_corpus):
    c = _cache(a["celex"])
    if not c.exists():
        return None
    with gzip.open(c, "rt", encoding="utf-8") as fh:
        reg = json.load(fh)
    destino = SAIDA / pasta(a["celex"]) / f"{nome_ficheiro(a['celex'])}.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    if "texto" not in reg:
        estado = "sem texto no Cellar (PT, EN, FR, DE)"
        corpo_md = ""
        partes = {"alteracoes": [], "preambulo": ""}
    else:
        partes = _corpo(reg["texto"], reg.get("formato"))
        corpo_md = partes["dispositivo"].strip()
        estado = ("consolidado" if reg.get("versao") else "original (JO)") + (" — PDF" if reg.get("formato") == "pdf" else "")
        if reg.get("lingua"):
            estado += f" — em {reg['lingua']}"
    fm = {
        "celex": a["celex"],
        "tipo": a.get("tipo"),
        "titulo": a.get("titulo"),
        "data_documento": a.get("data"),
        "estado": a["estado"],
        "entrada_em_vigor": a.get("entrada_em_vigor"),
        "texto": estado,
        "versao_consolidada": reg.get("versao"),
        "versao_aplicavel_desde": reg.get("versao_data"),
        "consolidacoes_sem_texto_pt": [f"{c} ({d})" for c, d in reg.get("versoes_sem_pt", [])] or None,
        "versao_futura": f"{reg['futuro_versao']} ({reg['futuro_data']})" if reg.get("futuro_versao") else None,
        "repertorio": a.get("repertorio") or None,
        "eli": a.get("eli") or None,
        "url_eurlex": eurlex.url_eurlex(a["celex"]),
        "corpus_curado": rel_corpus or None,
        "obtido_em": reg.get("obtido_em"),
    }
    fm = {k: v for k, v in fm.items() if v not in (None, "", [])}
    ls = [f"# {a.get('titulo') or a['celex']}", ""]
    if a["estado"] == "futuro":
        ls += [f"**Ainda não está em vigor:** entrada em vigor prevista a {a.get('entrada_em_vigor')}.", ""]
    if reg.get("versao"):
        ls += [f"**Texto:** versão consolidada aplicável desde {reg.get('versao_data')} ({reg['versao']}). "
               "Instrumento de documentação sem efeito jurídico; fazem fé os textos do Jornal Oficial.", ""]
    elif "texto" in reg:
        ls += ["**Texto:** versão original publicada no Jornal Oficial (sem alterações posteriores, se as houver).", ""]
    if reg.get("versoes_sem_pt"):
        ls += ["**Atenção:** há versões consolidadas mais recentes sem texto em português no Cellar: "
               + ", ".join(fm["consolidacoes_sem_texto_pt"]) + ".", ""]
    if reg.get("lingua"):
        nome = {"eng": "inglês", "fra": "francês", "deu": "alemão"}[reg["lingua"]]
        ls += [f"**Língua:** o Cellar não tem este acto em português; o texto abaixo está em **{nome}**.", ""]
    if reg.get("formato") == "pdf":
        ls += ["**Formato:** o Cellar só tem este texto em PDF; foi extraído automaticamente e pode ter "
               "quebras de linha e tabelas desalinhadas.", ""]
    if rel_corpus:
        ls += [f"**Versão curada** (com considerandos, sínteses, transposição e jurisprudência): `{rel_corpus}`.", ""]
    if reg.get("futuro_versao"):
        ls += [f"**Versão futura:** `{nome_ficheiro(a['celex'])}.futuro.md` (aplicável a partir de {reg['futuro_data']}).", ""]
    if partes.get("alteracoes"):
        ls += ["## Alterações incorporadas", ""] + [f"- {x['marca']} {x['descricao']} (CELEX {x['celex']})"
                                                    for x in partes["alteracoes"]] + [""]
    if partes.get("preambulo"):
        ls += ["## Preâmbulo", "", partes["preambulo"].strip(), ""]
    if corpo_md:
        ls += ["## Texto", "", corpo_md]
    elif "texto" not in reg:
        ls += ["O Cellar não tem texto deste acto em português, inglês, francês ou alemão (nem HTML nem "
               "PDF). Nos artigos isolados dos Tratados, o texto está na versão consolidada do Tratado "
               "respectivo. Ver o EUR-Lex.", ""]
    destino.write_text(eurlex._frontmatter(fm) + "\n".join(ls).rstrip() + "\n", encoding="utf-8")
    fut = destino.with_name(f"{nome_ficheiro(a['celex'])}.futuro.md")
    if reg.get("futuro_texto"):
        pf = _corpo(reg["futuro_texto"], reg.get("futuro_formato"))
        fmf = {"celex": a["celex"], "versao_consolidada": reg["futuro_versao"], "aplicavel_desde": reg["futuro_data"],
               "nota": "Versão consolidada já publicada que só se aplica a partir da data indicada.",
               "url_eurlex": eurlex.url_eurlex(reg["futuro_versao"]), "obtido_em": reg.get("obtido_em")}
        fut.write_text(eurlex._frontmatter(fmf) + f"# {a.get('titulo') or a['celex']} — versão aplicável a partir de "
                       f"{reg['futuro_data']}\n\n## Texto\n\n" + pf["dispositivo"].strip() + "\n", encoding="utf-8")
    elif fut.exists():
        fut.unlink()
    return {"celex": a["celex"], "ficheiro": str(destino.relative_to(RAIZ)), "estado": a["estado"], "texto": estado,
            "versao": reg.get("versao_data") or "", "futuro": reg.get("futuro_data") or "",
            "kb": destino.stat().st_size // 1024}


def mapa_corpus():
    res = {}
    for f in eurlex.CORPUS.glob("*/*.md"):
        if f.name.endswith((".considerandos.md", ".contexto.md")) or f.parent.name.startswith("_"):
            continue
        fm = eurlex.ler_frontmatter(f)
        if fm.get("celex"):
            res[fm["celex"]] = str(f.relative_to(RAIZ))
    return res


def cmd_converter(fios=4, so=None):
    actos = json.loads(LISTA.read_text(encoding="utf-8"))
    corpus = mapa_corpus()
    alvo = [a for a in actos.values() if not so or a["celex"] in so]
    linhas = []
    with cf.ProcessPoolExecutor(max_workers=fios) as ex:
        for r in ex.map(converter_um, alvo, [corpus.get(a["celex"]) for a in alvo], chunksize=50):
            if r:
                linhas.append(r)
    # Índice: substitui as linhas convertidas agora e mantém as restantes.
    antigas = {}
    if INDICE.exists() and so:
        with open(INDICE, encoding="utf-8", newline="") as fh:
            antigas = {l["celex"]: l for l in csv.DictReader(fh, delimiter="\t")}
    for l in linhas:
        antigas[l["celex"]] = l
    validos = set(actos)
    campos = ["celex", "estado", "texto", "versao", "futuro", "kb", "ficheiro"]
    SAIDA.mkdir(exist_ok=True)
    with open(INDICE, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(campos)
        for c in sorted(antigas):
            if c in validos:
                w.writerow([antigas[c].get(k, "") for k in campos])
    return linhas


def remover_obsoletos():
    """Apaga de ue/ os ficheiros de actos que deixaram de estar na lista (deixaram de vigorar)."""
    actos = json.loads(LISTA.read_text(encoding="utf-8"))
    validos = {nome_ficheiro(c) for c in actos}
    removidos = []
    for f in SAIDA.glob("*/*/*.md"):
        base = f.name[:-3].removesuffix(".futuro")
        if base not in validos:
            removidos.append(str(f.relative_to(RAIZ)))
            f.unlink()
    return removidos


def cmd_actualizar(fios=6):
    """Para a actualização automática: refaz as listas, descarrega o que é novo ou mudou de
    versão e reconverte só isso."""
    anterior = {}
    if INDICE.exists():
        with open(INDICE, encoding="utf-8", newline="") as fh:
            anterior = {l["celex"]: l for l in csv.DictReader(fh, delimiter="\t")}
    actos = cmd_listas()
    hoje = dt.date.today().isoformat()
    mudados = []
    for c, a in actos.items():
        vig, fut = plano(a, hoje)
        esperado = vig[0][1] if vig else ""
        ant = anterior.get(c)
        if ant is None or ant["versao"] != esperado or ant["futuro"] != (fut[1] if fut else "") \
                or ant["estado"] != a["estado"]:
            mudados.append(c)
            cache = _cache(c)
            if cache.exists():
                cache.unlink()
    print(f"{len(mudados)} actos novos ou com nova versão")
    if mudados:
        cmd_descarregar(fios, so=set(mudados))
        cmd_converter(so=set(mudados))
    removidos = remover_obsoletos()
    with open(SAIDA / "ALTERACOES.md", "a", encoding="utf-8") as fh:
        fh.write(f"\n## {hoje}\n\n- {len(mudados)} actos novos ou com nova versão consolidada\n"
                 f"- {len(removidos)} ficheiros removidos (actos que deixaram de estar em vigor)\n")
        for c in sorted(mudados)[:500]:
            fh.write(f"  - actualizado: {c}\n")
        for r in removidos[:500]:
            fh.write(f"  - removido: {r}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("passo", choices=["listas", "descarregar", "converter", "actualizar"])
    ap.add_argument("--fios", type=int, default=8)
    ap.add_argument("--limite", type=int)
    ap.add_argument("--so", nargs="*")
    a = ap.parse_args()
    if a.passo == "listas":
        cmd_listas()
    elif a.passo == "descarregar":
        print(cmd_descarregar(a.fios, set(a.so) if a.so else None, a.limite))
    elif a.passo == "converter":
        print(f"{len(cmd_converter(min(a.fios, 4), set(a.so) if a.so else None))} ficheiros")
    elif a.passo == "actualizar":
        cmd_actualizar(a.fios)


if __name__ == "__main__":
    main()
