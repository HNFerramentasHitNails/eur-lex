# Instruções para o Claude — corpus de direito da UE (EUR-Lex)

Este repositório contém legislação da União Europeia em português, extraída do EUR-Lex
(via Cellar, o repositório oficial do Serviço das Publicações da UE) e convertida para
Markdown. Serve de base para responder a perguntas, desenhar aplicações, bots e processos
que cumpram o direito da UE.

Responde sempre em português de Portugal.

## Onde está cada coisa

| Caminho | O que tem |
|---|---|
| `corpus/INDICE.md` | **Começa aqui.** Os 86 actos curados por área (com considerandos, sínteses, transposição e jurisprudência). |
| `ue/<tipo>/<ano>/<CELEX>.md` | **Texto integral de toda a legislação da UE em vigor** (≈64 mil actos) e dos actos já publicados que entram em vigor no futuro. Tipos: `regulamentos`, `diretivas`, `decisoes`, `tratados`, `acordos-internacionais`, `recomendacoes`, `concentracoes`, … Versão consolidada mais recente já aplicável, ou o original do JO. |
| `ue/<…>/<CELEX>.futuro.md` | Versão consolidada já publicada que só se aplica numa data futura (indicada no ficheiro). |
| `ue/INDICE.tsv` | Uma linha por acto de `ue/`: `celex`, `estado` (em vigor / futuro), `texto` (consolidado, original, PDF, outra língua, sem texto), data da versão, versão futura, tamanho, ficheiro. |
| `ue/ALTERACOES.md` | Registo das actualizações automáticas (actos novos, novas versões, removidos por deixarem de vigorar). |
| `corpus/<area>/<CELEX>-<nome>.md` | Texto do acto: versão consolidada mais recente já aplicável (ou o original do JO se não houver consolidação). Artigos como `### Artigo 6.º — Título`; capítulos, secções e anexos como `## …`. |
| `corpus/<area>/<…>.considerandos.md` | Preâmbulo (considerandos) do texto original. Os considerandos não são normas, mas explicam a intenção do legislador e o Tribunal de Justiça usa-os para interpretar. |
| `corpus/<area>/<…>.contexto.md` | Sínteses oficiais, **medidas portuguesas de transposição** (só diretivas) e lista de acórdãos do Tribunal de Justiça que interpretam o acto. |
| `corpus/_sinteses/<id>.md` | Sínteses oficiais da UE em linguagem simples (não são texto legal). |
| `legislacao-pt/INDICE.md` | Leis portuguesas que transpõem as diretivas do corpus, agrupadas por diretiva, com o estado de cada uma (consolidado, original, revogado, não obtido e porquê). |
| `legislacao-pt/<tipo>-<numero>-<ano>.md` | Texto do diploma português obtido no Diário da República Eletrónico: versão consolidada do DRE quando existe (com a origem de cada alteração em linhas `> Alterado pelo/a …`), senão o texto original publicado. Diplomas revogados ficam só com metadados. |
| `catalogo/legislacao-em-vigor.tsv` | Uma linha por cada um dos 64 273 actos marcados "em vigor" no Cellar em 2026-10-09 (tratados, acordos internacionais, regulamentos, diretivas, decisões…). Colunas: `celex`, `data`, `tipo`, `consolidado_ate` (data da versão consolidada mais recente, se houver), `repertorio` (códigos de área), `titulo` (PT), `eli`, `url`. Serve para descobrir o que existe; o texto só está no corpus para os actos do índice. |
| `catalogo/repertorio.md` | Árvore de áreas do repertório oficial do EUR-Lex, com contagens. |
| `ferramentas/eurlex.py` | Script que descarrega e converte. `ferramentas/nucleo.yaml` é a lista curada. |

Cada ficheiro começa com metadados YAML: `celex`, `titulo`, `em_vigor`, `texto`
(consolidado/original), `versao_aplicavel_desde`, `versoes_futuras`, `url_eurlex`,
`obtido_em` e, quando existem, dois avisos que **tens de ter em conta**:

- `consolidacoes_sem_texto_na_lingua`: há uma versão consolidada mais recente, com
  alterações, que o Cellar não tem em português. O ficheiro não inclui essas alterações;
  os actos alteradores vêm indicados (descarrega-os ou avisa).
- `rectificacoes_nao_incorporadas`: o texto é o original do JO e há rectificações
  publicadas depois que não estão aplicadas. Muitas só corrigem outras línguas; não se
  sabe, sem abrir cada uma, se mudam o texto português.

## Como responder a uma pergunta

1. Identifica o acto. Primeiro em `corpus/INDICE.md` (86 actos curados, mais completos).
   Se não estiver lá, procura no catálogo (`grep -i "palavra" catalogo/legislacao-em-vigor.tsv
   | cut -f1,2,3,6`, ou por área com o código de `catalogo/repertorio.md`) e lê o texto em
   `ue/` (o caminho está em `ue/INDICE.tsv`). Para pesquisar no texto de toda a legislação,
   usa `rg` (ripgrep) em `ue/` — são cerca de 1,5 GB, `grep -r` é lento.
   Se um acto do catálogo não estiver em `ue/`, descarrega-o:
   `python3 ferramentas/eurlex.py obter <CELEX> --area <area> --curto "<nome>"`.
2. Vai ao artigo concreto (`grep -n "^### Artigo 6.º" corpus/dados-e-privacidade/32016R0679-rgpd.md`)
   e lê-o inteiro, incluindo definições (normalmente no artigo 2.º, 3.º ou 4.º) e exceções.
   Usa os considerandos para a interpretação e o `.contexto.md` para a jurisprudência.
3. **Cita sempre a fonte exacta**: acto, artigo, número e alínea, a versão usada
   (`versao_aplicavel_desde`) e o ficheiro. Ex.: "RGPD, artigo 6.º, n.º 1, alínea f)
   (versão consolidada de 2016-05-04, `corpus/dados-e-privacidade/32016R0679-rgpd.md`)".
4. **Distingue o que está no texto do que é interpretação tua.** Se não encontraste a regra
   no corpus, diz "não encontrei no corpus" e como procuraste — não preenchas com memória.
5. Diz sempre o que fica por verificar (ver limites abaixo).

## Limites que tens de assinalar nas respostas

- **Diretivas não se aplicam directamente às empresas.** Obrigam os Estados-Membros a
  transpor. Para uma empresa em Portugal, a regra aplicável é a lei portuguesa de
  transposição: está listada no `.contexto.md` (secção "Transposição em Portugal") e, quando
  foi possível obtê-la, o texto está em `legislacao-pt/`. **Cita a lei portuguesa** quando a
  pergunta é sobre o que uma empresa em Portugal tem de fazer, e a diretiva como origem.
  A lei nacional pode ir além da diretiva quando a diretiva o permite.
- **A lista de transposição é a que Portugal comunicou à Comissão** (dados do Cellar). Pode
  incluir diplomas que só tocam o tema de lado, e pode faltar o diploma mais recente. Se o
  ficheiro em `legislacao-pt/` diz `original (DRE)`, alterações posteriores **não** estão
  incorporadas. Se diz `revogado`, procura no DRE o diploma que o substituiu.
- **Diplomas de alteração** (sumário "Altera…"): no texto original, os artigos da lei
  alterada que o diploma reproduz aparecem também como `### Artigo …`. Lê o artigo de
  alteração que os introduz antes de concluir de que lei é cada artigo.
- **Leis que aprovam um código em anexo** (ex.: `lei-7-2009.md`, Código do Trabalho): os
  primeiros artigos são da lei de aprovação; os artigos do código vêm depois de
  `## Anexo — CÓDIGO DO TRABALHO`. Confirma em que parte estás antes de citar "artigo N.º".
- **Regulamentos aplicam-se directamente**, mas muitos deixam margem aos Estados-Membros
  (o próprio texto diz quando: "o direito do Estado-Membro pode…"). Nesses pontos, a
  resposta depende da lei portuguesa.
- **Fiscalidade directa, segurança social, licenciamento, taxas de IVA concretas, prazos e
  procedimentos nacionais** são matéria nacional e, fora das leis de transposição, **não
  estão aqui**. A Diretiva IVA, por exemplo, fixa regras e limites; as taxas portuguesas
  estão no Código do IVA, que não foi descarregado.
- **Textos consolidados não têm valor jurídico** (aviso oficial do EUR-Lex): fazem fé os
  textos publicados no Jornal Oficial. Para decisões com consequências, confirmar no
  JO através de `url_eurlex`.
- **Datas:** o corpus foi obtido na data indicada em `obtido_em`. Se o ficheiro tiver
  `versoes_futuras`, há alterações já publicadas que ainda não se aplicam — diz isso se a
  pergunta for sobre o futuro. Se a pergunta for sobre o passado, a versão do corpus pode
  não ser a aplicável nessa data.
- **Orientações das autoridades** (Comissão, CEPD/EDPB, CNPD, ASAE, AT, Infarmed…) e
  normas técnicas harmonizadas (EN/ISO) não estão aqui, e muitas vezes são o que decide a
  prática.

Quando a resposta tiver consequências sérias (contratos, coimas, declarações fiscais,
colocação de produtos no mercado), diz claramente que é uma leitura do texto legal da UE
e que a aplicação ao caso concreto, sobretudo onde entra lei nacional, deve ser validada
por um profissional.

## Particularidades de `ue/`

- Ficheiros com `texto: … — em eng/fra/deu`: o Cellar não tem versão portuguesa (típico das
  decisões sobre concentrações, só na língua do processo). Diz ao utilizador que leste o
  texto noutra língua.
- `texto: … — PDF`: texto extraído de PDF; quebras de linha e tabelas podem estar
  desalinhadas.
- `texto: sem texto no Cellar …`: só metadados. Nos artigos isolados dos Tratados (CELEX
  como `12010E355`), lê a versão consolidada do Tratado respectivo.
- `estado: futuro`: o acto já foi publicado mas ainda não está em vigor (`entrada_em_vigor`).
- Os ficheiros de `ue/` não têm considerandos separados nem contexto: nos textos originais o
  preâmbulo vem na secção `## Preâmbulo`; nos consolidados não existe (está no JO).

## Actualização automática

`.github/workflows/actualizar.yml` corre às segundas-feiras: refaz o catálogo, descarrega os
actos novos ou com nova versão consolidada, remove de `ue/` os que deixaram de vigorar,
actualiza as leis portuguesas e o corpus curado, e faz commit. O que mudou fica em
`ue/ALTERACOES.md`. Antes de responder sobre algo muito recente, vê a data do último commit
ou o `obtido_em` do ficheiro.

## Convenções do texto convertido

- `▼B`, `▼M1`, `►M1 … ◄`, `▼C1`: marcas do EUR-Lex nos consolidados. `B` = texto de base,
  `M1`, `M2`… = alterado pelo acto listado em "Alterações incorporadas" no topo do ficheiro,
  `C1`… = rectificação, `A1`… = acto de adesão.
- `[^1]` = chamada de nota; a nota aparece como `[^1]: …` mais abaixo (normalmente no fim
  da secção ou do documento). A numeração pode repetir-se em secções diferentes.
- Alíneas e pontos estão como listas (`- a) …`, `- 1) …`), com subalíneas indentadas.
- Tabelas dos anexos estão em tabelas Markdown. Quando uma célula do original ocupa
  várias linhas (ex.: o nome de uma substância com várias restrições), é repetida em
  cada linha, ou aparece `(idem)` se for longa. Na 1.ª linha de algumas tabelas o
  cabeçalho original tinha várias linhas; lê as 2–3 primeiras linhas para perceber as
  colunas. Em caso de dúvida, confirmar no EUR-Lex.
- Imagens (símbolos, fórmulas) aparecem como `[imagem]`.

## Actualizar o corpus

```bash
pip install -r requirements.txt
python3 ferramentas/eurlex.py nucleo                    # todos os actos da lista curada
python3 ferramentas/eurlex.py nucleo --so 32016R0679    # só um
python3 ferramentas/eurlex.py obter 62014CJ0362 --area jurisprudencia --curto "Schrems"
python3 ferramentas/eurlex.py catalogo                  # catálogo de tudo o que está em vigor
python3 ferramentas/eurlex.py indice                    # regenerar corpus/INDICE.md
python3 ferramentas/dre.py tudo                         # leis portuguesas (precisa de Node + Playwright)
python3 ferramentas/completo.py listas && python3 ferramentas/completo.py descarregar && python3 ferramentas/completo.py converter   # tudo em vigor
python3 ferramentas/completo.py actualizar              # só o que é novo ou mudou
```

Para juntar uma lei portuguesa que não seja de transposição (ex.: execução de um
regulamento), acrescenta-a a `ferramentas/dre_extra.yaml` com a fonte que confirma a
relação, e corre `python3 ferramentas/dre.py tudo` e `python3 ferramentas/eurlex.py nucleo`.

O script usa o Cellar (publications.europa.eu) com 1 s entre pedidos; só recorre ao site
eur-lex.europa.eu quando o Cellar não tem o texto, e aí respeita os 10 s do robots.txt.
