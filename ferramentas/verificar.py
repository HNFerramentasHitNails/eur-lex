#!/usr/bin/env python3
"""Verificação automática depois de cada actualização: confronta os dados entre si e regista o
resultado em ue/ALTERACOES.md.

Os metadados do Cellar têm falhas que não dão erro (marcas "em vigor" atrasadas, datas de
aplicação registadas como entrada em vigor, MIN/MAX do SPARQL com datas de outros actos). Esta
verificação existe para que uma falha dessas apareça na semana em que acontece, em vez de passar
despercebida.

  python3 ferramentas/verificar.py                    corre as verificações e escreve o resultado
  python3 ferramentas/verificar.py --falhar-se-grave  sai com erro se a última verificação teve
                                                      problemas graves (ou não chegou a correr)
"""

import argparse
import csv
import datetime as dt
import io
import json
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import completo as C  # noqa: E402
import eurlex  # noqa: E402

RESULTADO = C.RAIZ / ".cache" / "verificacao.json"
MAX_REMOVIDOS = 100      # mais do que isto numa semana é suspeito
MAX_QUEDA = 0.01         # o número de actos não deve cair mais de 1 % de uma vez
MAX_TITULOS = 50         # títulos sem o número do acto (em 2026-10-10 eram 15, falhas do título oficial)
DIAS_POR_CONFIRMAR = 30  # a partir daqui, um acto "por confirmar" merece atenção


def ler_tsv(texto):
    return list(csv.DictReader(io.StringIO(texto), delimiter="\t"))


def verificar():
    hoje = dt.date.today()
    graves, avisos, ok = [], [], []
    indice = ler_tsv(C.INDICE.read_text(encoding="utf-8"))
    actos = {}
    if not C.LISTA.exists():
        graves.append("não há lista de actos (.cache/ue/lista.json): o passo de actualização falhou?")
    elif dt.date.fromtimestamp(C.LISTA.stat().st_mtime) != hoje:
        graves.append("a lista de actos não é de hoje: o passo de actualização falhou?")
    else:
        actos = json.loads(C.LISTA.read_text(encoding="utf-8"))
    por_celex = {l["celex"]: l for l in indice}

    # 1. Índice e ficheiros coincidem.
    sem_ficheiro = [l["celex"] for l in indice if not (C.RAIZ / l["ficheiro"]).exists()]
    listados = {l["ficheiro"] for l in indice}
    sem_linha = [str(f.relative_to(C.RAIZ)) for f in C.SAIDA.glob("*/*/*.md")
                 if not re.search(r"\.(futuro|parte-\d+)\.md$", f.name) and str(f.relative_to(C.RAIZ)) not in listados]
    if sem_ficheiro or sem_linha:
        graves.append(f"ue/INDICE.tsv e ue/ não coincidem: {len(sem_ficheiro)} linhas sem ficheiro "
                      f"(ex.: {sem_ficheiro[:3]}), {len(sem_linha)} ficheiros sem linha (ex.: {sem_linha[:3]})")
    else:
        ok.append(f"{len(indice)} actos em ue/INDICE.tsv, todos com ficheiro, e nenhum ficheiro sem linha")

    # 2. Linhas sem assinatura (fariam voltar a descarregar o acto na semana seguinte).
    sem_assin = [l["celex"] for l in indice if not l.get("assinatura")]
    if sem_assin:
        graves.append(f"{len(sem_assin)} linhas de ue/INDICE.tsv sem assinatura (ex.: {sem_assin[:3]})")

    # 3. Queda brusca do número de actos face ao último commit.
    try:
        antes = ler_tsv(subprocess.run(["git", "show", "HEAD:ue/INDICE.tsv"], cwd=C.RAIZ, capture_output=True,
                                       text=True, check=True).stdout)
        if len(indice) < len(antes) * (1 - MAX_QUEDA):
            graves.append(f"o número de actos caiu de {len(antes)} para {len(indice)} (mais de {MAX_QUEDA:.0%})")
        else:
            ok.append(f"número de actos: {len(antes)} no último commit, {len(indice)} agora")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        avisos.append(f"não foi possível comparar com o último commit ({e})")

    # 4. Remoções desta actualização: quantas e com que prova.
    removidos = json.loads(C.REMOVIDOS.read_text(encoding="utf-8")) if C.REMOVIDOS.exists() else {}
    if len(removidos) > MAX_REMOVIDOS:
        graves.append(f"{len(removidos)} actos dados como já não estando em vigor nesta actualização "
                      f"(mais de {MAX_REMOVIDOS}); confirmar antes de aceitar")
    elif removidos:
        ok.append(f"{len(removidos)} actos saem por já não estarem em vigor, todos com prova: "
                  + "; ".join(f"{c} ({m})" for c, m in sorted(removidos.items())[:10]))

    # 5. Classificação: estado da lista = estado do índice; nenhum "futuro" com data já passada.
    if actos:
        fut_passado = [c for c, a in actos.items() if a["estado"] == "futuro"
                       and (a.get("entrada_em_vigor") or "9999") <= hoje.isoformat()]
        if fut_passado:
            graves.append(f"{len(fut_passado)} actos 'futuro' com data de entrada em vigor já passada "
                          f"(ex.: {fut_passado[:3]})")
        dif = [c for c, a in actos.items() if c in por_celex and por_celex[c]["estado"] != a["estado"]]
        if dif:
            avisos.append(f"{len(dif)} actos com estado diferente na lista e em ue/INDICE.tsv (ex.: {dif[:3]})")
        falta = [c for c in actos if c not in por_celex]
        if falta:
            avisos.append(f"{len(falta)} actos da lista sem ficheiro em ue/ (descarga falhada?) (ex.: {falta[:5]})")
        conf = {c: a for c, a in actos.items() if a["estado"] == C.NAO_CONFIRMADO}
        antigos = [c for c, a in conf.items()
                   if (a.get("entrada_em_vigor") or "9999") < (hoje - dt.timedelta(days=DIAS_POR_CONFIRMAR)).isoformat()]
        if antigos:
            avisos.append(f"{len(antigos)} actos 'em vigor (por confirmar)' há mais de {DIAS_POR_CONFIRMAR} dias "
                          f"sem o Cellar os marcar: {', '.join(sorted(antigos)[:10])}")
        if conf:
            ok.append(f"{len(conf)} actos em vigor por confirmar no Cellar: {', '.join(sorted(conf)[:10])}")

    # 6. Catálogo: data da última consolidação = máximo das versões obtidas em linhas.
    catalogo = ler_tsv((eurlex.CATALOGO / "legislacao-em-vigor.tsv").read_text(encoding="utf-8"))
    if actos:
        dif = [l["celex"] for l in catalogo if l["celex"] in actos
               and l["consolidado_ate"] != max((v[1] for v in actos[l["celex"]].get("versoes", [])), default="")]
        if dif:
            graves.append(f"{len(dif)} actos com consolidado_ate no catálogo diferente da versão mais recente "
                          f"(ex.: {dif[:3]})")
        else:
            ok.append("consolidado_ate do catálogo coincide com as versões consolidadas em todos os actos")

    # 7. Títulos com o número do acto (detecta títulos trocados entre actos).
    sem_num = []
    for l in catalogo:
        m = re.match(r"^3(20(1[5-9]|[2-9]\d))([RLD])(\d{4})$", l["celex"])
        if m and not re.search(rf"\b{m.group(1)}/{int(m.group(4))}\b", l["titulo"]):
            sem_num.append(l["celex"])
    (avisos if len(sem_num) > MAX_TITULOS else ok).append(
        f"{len(sem_num)} títulos de regulamentos/diretivas/decisões desde 2015 sem o número do acto "
        f"(limite {MAX_TITULOS}){': ' + ', '.join(sem_num[:5]) if sem_num else ''}")
    return graves, avisos, ok


def escrever(graves, avisos, ok):
    hoje = dt.date.today().isoformat()
    ls = [f"\n### Verificação automática ({hoje})\n"]
    ls += [f"- **Grave:** {g}" for g in graves] + [f"- **Aviso:** {a}" for a in avisos] + [f"- OK: {o}" for o in ok]
    with open(C.SAIDA / "ALTERACOES.md", "a", encoding="utf-8") as fh:
        fh.write("\n".join(ls) + "\n")
    RESULTADO.parent.mkdir(exist_ok=True)
    RESULTADO.write_text(json.dumps({"data": hoje, "graves": graves, "avisos": avisos, "ok": ok},
                                    ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(ls))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--falhar-se-grave", action="store_true")
    a = ap.parse_args()
    if a.falhar_se_grave:
        if not RESULTADO.exists():
            sys.exit("A verificação não chegou a correr.")
        r = json.loads(RESULTADO.read_text(encoding="utf-8"))
        if r["data"] != dt.date.today().isoformat():
            sys.exit(f"A última verificação é de {r['data']}, não de hoje.")
        if r["graves"]:
            sys.exit("Problemas graves (ver ue/ALTERACOES.md):\n- " + "\n- ".join(r["graves"]))
        print("Verificação sem problemas graves.")
        return
    escrever(*verificar())


if __name__ == "__main__":
    main()
