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
import http.client
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
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, http.client.HTTPException):
                pass  # inclui IncompleteRead em documentos muito grandes: tenta outra vez
            time.sleep(2 ** (n + 1))
        else:
            return 0, "", b""
    return 0, "", b""


def conteudo(celex, lingua="por"):
    """(texto, formato) do acto na língua pedida: XHTML, HTML ou, em último caso, PDF -> texto."""
    url = CELLAR + urllib.parse.quote(celex, safe="")
    for aceitar, fmt in (("application/xhtml+xml", "html"), ("text/html", "html"), ("application/pdf", "pdf"),
                         ("application/msword", "doc")):
        estado, ctype, corpo = get(url, aceitar, lingua)
        if estado == 300:
            partes = []
            for doc in eurlex._documentos_300(corpo):
                e2, _, c2 = get(urllib.parse.urljoin(url, doc), aceitar, lingua)
                if e2 == 200:
                    partes.append(c2)
            if not partes:
                continue
            if fmt in ("pdf", "doc"):
                conv = pdf_texto if fmt == "pdf" else doc_texto
                return "\n\n".join(conv(p) for p in partes), fmt
            return sem_imagens("\n".join(p.decode("utf-8", "replace") for p in partes)), fmt
        if estado == 200 and corpo:
            if fmt in ("pdf", "doc"):
                return (pdf_texto if fmt == "pdf" else doc_texto)(corpo), fmt
            return sem_imagens(corpo.decode("utf-8", "replace")), fmt
    return None, None


RE_IMAGEM_EMBUTIDA = re.compile(r"data:image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+")


def sem_imagens(html):
    """Retira imagens embutidas em base64 (os regulamentos UNECE chegam a 27 MB só disso);
    o Markdown mostra-as como [imagem]."""
    return RE_IMAGEM_EMBUTIDA.sub("data:removida", html)


def doc_texto(dados):
    """Word (.doc) -> texto, com o LibreOffice sem interface (um perfil por fio de execução)."""
    with tempfile.TemporaryDirectory() as d:
        f = pathlib.Path(d) / "a.doc"
        f.write_bytes(dados)
        perfil = pathlib.Path(tempfile.gettempdir()) / f"lo-perfil-{threading.get_ident()}"
        subprocess.run(["soffice", "--headless", f"-env:UserInstallation=file://{perfil}",
                        "--convert-to", "txt:Text (encoded):UTF8", "--outdir", d, str(f)],
                       capture_output=True, timeout=300)
        txt = pathlib.Path(d) / "a.txt"
        return txt.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff") if txt.exists() else ""


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


NAO_CONFIRMADO = "em vigor (por confirmar)"
REMOVIDOS = CACHE / "removidos.json"  # actos que saem de ue/ nesta actualização e porquê


def _marca(v):
    return {"1": True, "true": True, "0": False, "false": False}.get(str(v).lower())


def estado_cellar(celexes, lote=80):
    """Marca 'em vigor', datas de fim de validade e de entrada em vigor, por CELEX (em linhas)."""
    res = {}
    celexes = sorted(celexes)
    for i in range(0, len(celexes), lote):
        valores = " ".join(eurlex._lit(c) for c in celexes[i:i + lote])
        for l in eurlex.sparql(eurlex.PREFIXOS + f"""
SELECT ?celex ?marca (STR(?f) AS ?fim) (STR(?eif) AS ?entrada) WHERE {{
  VALUES ?c {{ {valores} }}
  ?w cdm:resource_legal_id_celex ?c . BIND(STR(?c) AS ?celex)
  OPTIONAL {{ ?w cdm:resource_legal_in-force ?marca }}
  OPTIONAL {{ ?w cdm:resource_legal_date_end-of-validity ?f }}
  OPTIONAL {{ ?w cdm:resource_legal_date_entry-into-force ?eif }}
}}"""):
            r = res.setdefault(l["celex"], {"marca": None, "fim": set(), "entrada": set()})
            if l.get("marca") is not None:
                r["marca"] = _marca(l["marca"])
            if l.get("fim"):
                r["fim"].add(l["fim"][:10])
            if l.get("entrada"):
                r["entrada"].add(l["entrada"][:10])
    return res


def prova_cessacao(info, hoje, recente):
    """Motivo para dar um acto como já não estando em vigor, ou None se não houver prova. No sector
    3, 99,4 % dos actos marcados como não estando em vigor têm data de fim de validade (medido no
    Cellar em 2026-10-10: 75 668 de 76 144). A marca sozinha não chega: o Cellar marca 'false'
    actos que entram em vigor nesse dia (ex.: 32026D2204)."""
    if not info:
        return None
    fins = sorted(f for f in info["fim"] if f <= hoje)
    if fins:
        return f"fim de validade a {fins[0]}"
    if info["marca"] is False and (not info["entrada"] or min(info["entrada"]) < recente):
        return "marcado no Cellar como não estando em vigor" + \
            (f" (entrada em vigor a {min(info['entrada'])})" if info["entrada"] else "")
    return None


def cmd_listas():
    hoje_d = dt.date.today()
    hoje, recente = hoje_d.isoformat(), (hoje_d - dt.timedelta(days=365)).isoformat()
    actos = {}
    with open(eurlex.CATALOGO / "legislacao-em-vigor.tsv", encoding="utf-8", newline="") as fh:
        for l in csv.DictReader(fh, delimiter="\t"):
            actos[l["celex"]] = {"celex": l["celex"], "titulo": l["titulo"], "data": l["data"], "tipo": l["tipo"],
                                 "repertorio": l["repertorio"], "eli": l["eli"], "estado": "em vigor"}

    # Actos publicados que o Cellar não marca como em vigor, cuja validade não terminou e com alguma
    # data de entrada em vigor no último ano ou no futuro. As datas vêm em linhas e o mínimo é
    # calculado aqui (o MIN/MAX do Cellar dá datas de outros actos). Classificação:
    # - todas as datas depois de hoje → "futuro";
    # - a primeira já passou → "em vigor (por confirmar)": o Cellar demora dias a marcá-los, e
    #   regista as datas de aplicação diferida como datas de entrada em vigor (ex.: 32026L0806,
    #   em vigor desde 2026-05, com pontos aplicáveis em 2028, que aparecia como "futuro").
    linhas = eurlex.sparql(eurlex.PREFIXOS + f"""
SELECT ?celex (STR(?eif) AS ?entrada) ?t ?dd WHERE {{
  ?w cdm:resource_legal_id_celex ?celex ; cdm:resource_legal_date_entry-into-force ?eif .
  FILTER(REGEX(STR(?celex), "^[1234]"))
  FILTER NOT EXISTS {{ ?w cdm:resource_legal_in-force "true"^^xsd:boolean }}
  FILTER NOT EXISTS {{ ?w cdm:resource_legal_date_end-of-validity ?fim . FILTER(?fim <= "{hoje}"^^xsd:date) }}
  FILTER EXISTS {{ ?w cdm:resource_legal_date_entry-into-force ?e2 . FILTER(?e2 >= "{recente}"^^xsd:date) }}
  OPTIONAL {{ ?w cdm:work_date_document ?dd }}
  OPTIONAL {{ ?x cdm:expression_belongs_to_work ?w ;
               cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/POR> ;
               cdm:expression_title ?t }}
}}""")
    nao_marcados = {}
    for l in linhas:
        n = nao_marcados.setdefault(l["celex"], {"datas": set(), "titulo": "", "data": ""})
        n["datas"].add(l["entrada"][:10])
        n["titulo"] = n["titulo"] or l.get("t", "")
        n["data"] = n["data"] or (l.get("dd") or "")[:10]
    for c, n in nao_marcados.items():
        if c in actos:
            continue
        datas = sorted(n["datas"])
        futuras = [d for d in datas if d > hoje]
        if datas[0] > hoje:
            estado, nota = "futuro", None
        elif datas[0] >= recente or futuras:
            estado = NAO_CONFIRMADO
            nota = (f"entrou em vigor a {datas[0]} (data registada no Cellar), mas o Cellar ainda não o marca "
                    "como em vigor." + (f" Algumas disposições só se aplicam a partir de {', '.join(futuras)}."
                                        if futuras else ""))
        else:
            continue
        actos[c] = {"celex": c, "titulo": eurlex.limpar_titulo(n["titulo"]), "data": n["data"],
                    "tipo": eurlex.nome_tipo(c), "repertorio": "", "eli": "", "estado": estado,
                    "entrada_em_vigor": datas[0]}
        if nota:
            actos[c]["nota_estado"] = nota

    # Actos que estavam em ue/ e não vêm em nenhuma das listas: só saem com prova de que deixaram de
    # vigorar. Sem prova, ficam como "em vigor (por confirmar)" (antes eram apagados: em 2026-10-10
    # saíram assim 6 actos que entravam em vigor nesse dia e o Cellar ainda não tinha marcado).
    anteriores = {}
    if INDICE.exists():
        with open(INDICE, encoding="utf-8", newline="") as fh:
            anteriores = {l["celex"]: l["ficheiro"] for l in csv.DictReader(fh, delimiter="\t")}
    conhecidos = {nome_ficheiro(c) for c in anteriores}
    for f in SAIDA.glob("*/*/*.md"):
        base = re.sub(r"\.parte-\d+$", "", f.name[:-3]).removesuffix(".futuro")
        if base not in conhecidos and f.name == base + ".md":
            c = eurlex.ler_frontmatter(f).get("celex")
            if c:
                anteriores[c] = str(f.relative_to(RAIZ))
    saidos = [c for c in anteriores if c not in actos]
    info = estado_cellar(saidos) if saidos else {}
    removidos = {}
    for c in saidos:
        prova = prova_cessacao(info.get(c), hoje, recente)
        if prova:
            removidos[c] = prova
            continue
        fich = RAIZ / anteriores[c]
        fm = eurlex.ler_frontmatter(fich) if fich.exists() else {}
        i = info.get(c)
        if i is None:
            nota = "não foi encontrado no Cellar nesta actualização; mantido até haver confirmação."
        elif i["marca"]:
            nota = None
        else:
            nota = ("o Cellar não o marca como em vigor, mas também não indica fim de validade nem outra prova "
                    "de que deixou de vigorar; mantido até haver confirmação.")
        actos[c] = {"celex": c, "titulo": fm.get("titulo") or "", "data": str(fm.get("data_documento") or ""),
                    "tipo": fm.get("tipo") or eurlex.nome_tipo(c), "repertorio": str(fm.get("repertorio") or ""),
                    "eli": str(fm.get("eli") or ""), "estado": NAO_CONFIRMADO if nota else "em vigor"}
        if i and i["entrada"]:
            actos[c]["entrada_em_vigor"] = min(i["entrada"])
        if nota:
            actos[c]["nota_estado"] = nota

    # Versões consolidadas, por acto de base (em linhas; ver eurlex.versoes_consolidadas_todas).
    versoes = eurlex.versoes_consolidadas_todas()
    for base, cc, d in versoes:
        a = actos.get(base)
        if a is not None:
            a.setdefault("versoes", []).append([cc, d])
    for a in actos.values():
        a["versoes"] = sorted({tuple(v) for v in a.get("versoes", [])}, key=lambda v: v[1], reverse=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    LISTA.write_text(json.dumps(actos, ensure_ascii=False), encoding="utf-8")
    REMOVIDOS.write_text(json.dumps(removidos, ensure_ascii=False, indent=0), encoding="utf-8")
    n_fut = sum(1 for a in actos.values() if a["estado"] == "futuro")
    n_conf = sum(1 for a in actos.values() if a["estado"] == NAO_CONFIRMADO)
    n_cons = sum(1 for a in actos.values() if a["versoes"])
    print(f"{len(actos)} actos ({n_fut} futuros, {n_conf} em vigor por confirmar no Cellar); "
          f"{n_cons} com versões consolidadas; {len(versoes)} versões; {len(removidos)} deixam de estar em vigor")
    return actos


# ---------------------------------------------------------------------------
# Descarga
# ---------------------------------------------------------------------------

def _cache(celex):
    return CACHE / "html" / pasta(celex) / f"{nome_ficheiro(celex)}.json.gz"


def assinatura(a, hoje):
    """O que se pretende obter para o acto hoje (haja ou não texto em português): a versão
    consolidada aplicável mais recente, a futura e o estado. Muda quando há uma versão nova."""
    vig, fut = plano(a, hoje)
    return f"{vig[0][0] if vig else ''}|{fut[0] if fut else ''}|{a['estado']}"


def assinatura_fm(fm):
    """A mesma assinatura, reconstruída a partir do frontmatter de um ficheiro de ue/ (para
    ficheiros gerados antes de a assinatura ser guardada). Se a versão futura não tinha texto
    em português, não ficou registada: a assinatura não coincide e o acto volta a ser obtido."""
    sem_pt = fm.get("consolidacoes_sem_texto_pt") or []
    vig = sem_pt[0].split(" ")[0] if sem_pt else (fm.get("versao_consolidada") or "")
    fut = (fm.get("versao_futura") or "").split(" ")[0]
    return f"{vig}|{fut}|{fm.get('estado', '')}"


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
    reg = {"celex": a["celex"], "obtido_em": hoje, "assinatura": assinatura(a, hoje)}
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

LIMIAR_LEVE = 30_000_000   # caracteres de HTML a partir dos quais não se constrói a árvore
LIMITE_FICHEIRO = 45_000_000  # bytes; o GitHub recusa ficheiros acima de 100 MB


def _leve(html):
    """Conversão simplificada para documentos enormes (tabelas de centenas de MB): retira as
    marcas com expressões regulares em vez de construir a árvore HTML, que não cabe em memória."""
    import html as html_lib
    t = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", html)
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = re.sub(r"(?i)</(p|div|h[1-6]|li|tr|table|caption)>", "\n", t)
    t = re.sub(r"(?i)</t[dh]>", " | ", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html_lib.unescape(t)
    out = []
    for linha in t.split("\n"):
        linha = re.sub(r"[ \t\xa0]+", " ", linha).strip(" |")
        if not linha:
            continue
        if re.match(r"^Artigo \d+\.?\s*[ºo°]?(-[A-Z])?$", linha):
            out.append("### " + eurlex._normalizar_artigo(linha))
        elif re.match(r"^(ANEXO|CAPÍTULO|TÍTULO|PARTE|SECÇÃO)\b", linha) and len(linha) < 80:
            out.append("## " + linha)
        else:
            out.append(linha)
    return "\n\n".join(out)


def _corpo(texto, formato):
    if formato == "doc":
        pars = [re.sub(r"[ \t\xa0]+", " ", l).strip() for l in texto.splitlines()]
        return {"alteracoes": [], "preambulo": "", "dispositivo": "\n\n".join(p for p in pars if p)}
    if formato != "pdf" and len(texto) > LIMIAR_LEVE:
        return {"alteracoes": [], "preambulo": "", "dispositivo": _leve(texto), "leve": True}
    if formato == "pdf":
        t = re.sub(r"[ \t]+\n", "\n", texto)
        return {"alteracoes": [], "preambulo": "", "dispositivo": "```text\n" + t.strip() + "\n```"}
    return eurlex.analisar(texto)


def _linha_existente(a, destino):
    fm = eurlex.ler_frontmatter(destino)
    return {"celex": a["celex"], "ficheiro": str(destino.relative_to(RAIZ)), "estado": a["estado"],
            "texto": fm.get("texto", ""), "versao": fm.get("versao_aplicavel_desde") or "",
            "futuro": (fm.get("versao_futura") or "").split("(")[-1].rstrip(")") if fm.get("versao_futura") else "",
            "kb": destino.stat().st_size // 1024, "assinatura": assinatura_fm(fm)}


def converter_um(a, rel_corpus, so_novos=False):
    c = _cache(a["celex"])
    if not c.exists():
        return None
    destino = SAIDA / pasta(a["celex"]) / f"{nome_ficheiro(a['celex'])}.md"
    if so_novos and destino.exists() and destino.stat().st_mtime >= c.stat().st_mtime:
        return _linha_existente(a, destino)
    with gzip.open(c, "rt", encoding="utf-8") as fh:
        reg = json.load(fh)
    destino.parent.mkdir(parents=True, exist_ok=True)
    if "texto" not in reg:
        estado = "sem texto no Cellar (PT, EN, FR, DE; HTML, PDF, Word)"
        corpo_md = ""
        partes = {"alteracoes": [], "preambulo": ""}
    else:
        partes = _corpo(reg["texto"], reg.get("formato"))
        corpo_md = partes["dispositivo"].strip()
        estado = ("consolidado" if reg.get("versao") else "original (JO)") + \
            {"pdf": " — PDF", "doc": " — Word"}.get(reg.get("formato"), "")
        if reg.get("lingua"):
            estado += f" — em {reg['lingua']}"
    fm = {
        "celex": a["celex"],
        "tipo": a.get("tipo"),
        "titulo": a.get("titulo"),
        "data_documento": a.get("data"),
        "estado": a["estado"],
        "entrada_em_vigor": a.get("entrada_em_vigor"),
        "nota_estado": a.get("nota_estado"),
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
    elif a["estado"] == NAO_CONFIRMADO:
        nota = a.get("nota_estado") or ""
        ls += [f"**Em vigor, por confirmar:** {nota[:1].upper() + nota[1:]} Confirmar no EUR-Lex.", ""]
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
    if reg.get("formato") == "doc":
        ls += ["**Formato:** o Cellar só tem este texto em ficheiro Word; foi extraído automaticamente.", ""]
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
        ls += ["O Cellar não tem texto deste acto em português, inglês, francês ou alemão (nem HTML, nem "
               "PDF, nem Word). Nos artigos isolados dos Tratados, o texto está na versão consolidada do Tratado "
               "respectivo. Ver o EUR-Lex.", ""]
    if partes.get("leve"):
        ls.insert(2, "**Conversão simplificada:** documento muito grande (tabelas extensas); o texto foi "
                     "extraído sem a estrutura de listas e tabelas. As células de tabela vêm separadas por `|`.\n")
    escrever_em_partes(destino, eurlex._frontmatter(fm) + "\n".join(ls).rstrip() + "\n")
    fut = destino.with_name(f"{nome_ficheiro(a['celex'])}.futuro.md")
    if reg.get("futuro_texto"):
        pf = _corpo(reg["futuro_texto"], reg.get("futuro_formato"))
        fmf = {"celex": a["celex"], "versao_consolidada": reg["futuro_versao"], "aplicavel_desde": reg["futuro_data"],
               "nota": "Versão consolidada já publicada que só se aplica a partir da data indicada.",
               "url_eurlex": eurlex.url_eurlex(reg["futuro_versao"]), "obtido_em": reg.get("obtido_em")}
        escrever_em_partes(fut, eurlex._frontmatter(fmf) + f"# {a.get('titulo') or a['celex']} — versão aplicável "
                           f"a partir de {reg['futuro_data']}\n\n## Texto\n\n" + pf["dispositivo"].strip() + "\n")
    elif fut.exists():
        fut.unlink()
    return {"celex": a["celex"], "ficheiro": str(destino.relative_to(RAIZ)), "estado": a["estado"], "texto": estado,
            "versao": reg.get("versao_data") or "", "futuro": reg.get("futuro_data") or "",
            "kb": destino.stat().st_size // 1024, "assinatura": reg.get("assinatura") or assinatura_fm(fm)}


def escrever_em_partes(destino, texto):
    """Escreve o ficheiro; acima de LIMITE_FICHEIRO divide-o em <nome>.parte-N.md (pelas linhas)."""
    for antigo in destino.parent.glob(destino.name[:-3] + ".parte-*.md"):
        antigo.unlink()
    dados = texto.encode("utf-8")
    if len(dados) <= LIMITE_FICHEIRO:
        destino.write_bytes(dados)
        return
    partes, atual, tam = [], [], 0
    for linha in texto.splitlines(keepends=True):
        n = len(linha.encode("utf-8"))
        if tam + n > LIMITE_FICHEIRO - 2000 and atual:
            partes.append("".join(atual))
            atual, tam = [], 0
        atual.append(linha)
        tam += n
    partes.append("".join(atual))
    base = destino.name[:-3]
    nomes = [destino.name] + [f"{base}.parte-{i}.md" for i in range(2, len(partes) + 1)]
    aviso = (f"\n\n> Este acto é demasiado grande para um só ficheiro: está dividido em {len(partes)} partes "
             f"({', '.join(nomes)}).\n")
    destino.write_text(partes[0] + aviso, encoding="utf-8")
    for i, parte in enumerate(partes[1:], 2):
        (destino.parent / f"{base}.parte-{i}.md").write_text(
            f"<!-- {base} — parte {i} de {len(partes)} -->\n\n" + parte, encoding="utf-8")


def _tamanho_cache(celex):
    """Tamanho descomprimido do registo em cache (lido do fim do ficheiro gzip)."""
    import struct
    c = _cache(celex)
    if not c.exists():
        return 0
    with open(c, "rb") as fh:
        fh.seek(-4, 2)
        return struct.unpack("<I", fh.read(4))[0]


def mapa_corpus():
    res = {}
    for f in eurlex.CORPUS.glob("*/*.md"):
        if f.name.endswith((".considerandos.md", ".contexto.md")) or f.parent.name.startswith("_"):
            continue
        fm = eurlex.ler_frontmatter(f)
        if fm.get("celex"):
            res[fm["celex"]] = str(f.relative_to(RAIZ))
    return res


def cmd_converter(fios=4, so=None, so_novos=False):
    actos = json.loads(LISTA.read_text(encoding="utf-8"))
    corpus = mapa_corpus()
    alvo = [a for a in actos.values() if not so or a["celex"] in so]
    linhas = []
    gigantes = [a for a in alvo if _tamanho_cache(a["celex"]) > LIMIAR_LEVE]
    normais = [a for a in alvo if a not in gigantes] if gigantes else alvo
    with cf.ProcessPoolExecutor(max_workers=fios, max_tasks_per_child=200) as ex:
        for r in ex.map(converter_um, normais, [corpus.get(a["celex"]) for a in normais],
                        [so_novos] * len(normais), chunksize=20):
            if r:
                linhas.append(r)
    for a in gigantes:  # um de cada vez, no processo principal, para não esgotar a memória
        r = converter_um(a, corpus.get(a["celex"]), so_novos)
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
    campos = ["celex", "estado", "texto", "versao", "futuro", "kb", "ficheiro", "assinatura"]
    SAIDA.mkdir(exist_ok=True)
    with open(INDICE, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(campos)
        for c in sorted(antigas):
            if c in validos:
                w.writerow([antigas[c].get(k, "") for k in campos])
    return linhas


def remover_obsoletos():
    """Apaga de ue/ os ficheiros de actos que não estão na lista. cmd_listas só deixa sair da lista
    os actos com prova de que deixaram de vigorar (motivo em REMOVIDOS)."""
    actos = json.loads(LISTA.read_text(encoding="utf-8"))
    motivos = {nome_ficheiro(c): m for c, m in json.loads(REMOVIDOS.read_text(encoding="utf-8")).items()} \
        if REMOVIDOS.exists() else {}
    validos = {nome_ficheiro(c) for c in actos}
    removidos = []
    for f in SAIDA.glob("*/*/*.md"):
        base = re.sub(r"\.parte-\d+$", "", f.name[:-3]).removesuffix(".futuro")
        if base not in validos:
            removidos.append(f"{f.relative_to(RAIZ)} ({motivos.get(base, 'fora da lista')})")
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
        # Compara o que se pretendia obter da última vez com o que se pretende hoje (não a versão
        # obtida: quando a consolidação mais recente não tem texto em português usa-se outra, e
        # comparar datas fazia voltar a descarregar esses actos todas as semanas).
        ant = anterior.get(c)
        antes = (ant or {}).get("assinatura")
        if ant and not antes and (RAIZ / ant["ficheiro"]).exists():
            antes = assinatura_fm(eurlex.ler_frontmatter(RAIZ / ant["ficheiro"]))
        if ant is None or antes != assinatura(a, hoje):
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
    ap.add_argument("--so-novos", action="store_true", help="converter: saltar ficheiros já actualizados")
    a = ap.parse_args()
    if a.passo == "listas":
        cmd_listas()
    elif a.passo == "descarregar":
        print(cmd_descarregar(a.fios, set(a.so) if a.so else None, a.limite))
    elif a.passo == "converter":
        print(f"{len(cmd_converter(min(a.fios, 4), set(a.so) if a.so else None, a.so_novos))} ficheiros")
    elif a.passo == "actualizar":
        cmd_actualizar(a.fios)


if __name__ == "__main__":
    main()
