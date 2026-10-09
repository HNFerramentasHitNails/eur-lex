# EUR-Lex em Markdown — direito da UE para o Claude

Legislação da União Europeia em português, extraída da fonte oficial e convertida para
texto que o Claude (ou qualquer pessoa) consegue ler, pesquisar e citar. O objectivo é
servir de base a aplicações, bots, assistentes e perguntas sobre o que a UE exige.

**Não substitui um advogado, jurista ou contabilista.** Cobre o direito da UE e as leis
portuguesas que transpõem as diretivas do corpus; a maior parte das outras obrigações do
dia-a-dia de uma empresa em Portugal (impostos, segurança social, licenças, taxas de IVA)
está em lei portuguesa que não está aqui. Ver "O que não está aqui".

## O que está aqui

- **`corpus/`** — o texto completo de 86 actos escolhidos por serem os que um negócio
  digital, de comércio electrónico ou de produtos encontra na prática: tratados e Carta,
  RGPD e dados, IA e plataformas (Regulamento IA, DSA, DMA…), consumo e vendas online,
  contratos e litígios, segurança de produtos e **cosméticos** (Regulamento 1223/2009,
  CLP, REACH), equipamentos eléctricos e embalagens, IVA e alfândegas, contabilidade e
  apoios, pagamentos e cripto, trabalho, marcas e direitos de autor.
  Lista completa em [`corpus/INDICE.md`](corpus/INDICE.md); critérios em
  [`ferramentas/nucleo.yaml`](ferramentas/nucleo.yaml).
  Para cada acto:
  - o texto em vigor (versão consolidada mais recente já aplicável);
  - os considerandos (preâmbulo) do texto original;
  - um ficheiro de contexto com as sínteses oficiais em linguagem simples, as **leis
    portuguesas que transpõem cada diretiva** e os acórdãos do Tribunal de Justiça que
    interpretam o acto.
- **`legislacao-pt/`** — as leis portuguesas que Portugal comunicou à Comissão Europeia como
  transpondo as 46 diretivas do corpus, com o texto do Diário da República Eletrónico
  (versão consolidada do DRE quando existe, com a indicação do diploma que alterou cada
  artigo). Exemplo: a Diretiva 2011/83 (direitos dos consumidores) liga ao Decreto-Lei
  n.º 24/2014, consolidado até à alteração de 2023-03-03. Índice em
  [`legislacao-pt/INDICE.md`](legislacao-pt/INDICE.md), com o estado de cada diploma e a
  causa quando não foi possível obtê-lo. Em 2026-10-09: das 313 medidas registadas no
  Cellar, 110 têm versão consolidada, 123 só o texto original, 19 estão revogadas (só
  metadados) e 61 não foram obtidas (27 são declarações de retificação; as restantes causas
  estão no índice). A lista é a que Portugal comunicou: pode não incluir a lei em vigor
  mais recente sobre o tema.
- **`catalogo/`** — índice de **toda** a legislação da UE marcada como em vigor no Cellar:
  64 273 actos em 2026-10-09 (7 393 de tratados, 9 132 acordos internacionais, 16 244
  regulamentos, 1 305 diretivas, 17 490 decisões, 9 512 decisões sobre concentrações e
  outros), com título em PT, data, área do repertório oficial e ligação. Serve para saber
  o que existe e ir buscar o que faltar.
- **`ferramentas/eurlex.py`** — o script que faz a extracção e a conversão; permite
  acrescentar qualquer acto ou acórdão pelo número CELEX.
- **`CLAUDE.md`** — instruções para o Claude: como pesquisar, como citar e que limites
  assinalar nas respostas.

## Porque não está "todo o EUR-Lex"

O EUR-Lex tem cerca de 1 milhão de documentos (contagem de obras com número CELEX no
Cellar em 2026-10-09), cada um em até 24 línguas: legislação revogada, propostas,
trabalhos preparatórios, jurisprudência, perguntas parlamentares, Jornal Oficial série C…
Só a legislação derivada marcada como em vigor são ~47 000 actos, muitos deles decisões
sobre casos concretos (uma concentração de empresas, um auxílio a uma empresa, uma quota
de pesca).

Pôr tudo num repositório não ajuda o Claude a responder melhor — torna a pesquisa mais
lenta e mais ruidosa. Por isso a opção foi:

1. texto integral para o que é relevante para projectos de negócio (o núcleo);
2. catálogo completo do que está em vigor, para descobrir o resto;
3. ferramenta para descarregar qualquer outro acto quando for preciso.

## O que não está aqui

- Lei portuguesa que não seja de transposição das diretivas do corpus (ex.: Código do IVA,
  Código das Sociedades Comerciais, leis de execução de regulamentos — exceto as listadas
  em `ferramentas/dre_extra.yaml`). Diplomas regionais (Açores/Madeira) também não.
- Orientações e decisões de autoridades (Comissão, CEPD, CNPD, ASAE, AT, Infarmed…).
- Normas técnicas (EN, ISO), que não são publicadas no EUR-Lex.
- Texto integral da jurisprudência (só a lista; descarrega-se a pedido).
- Outras línguas além do português (o script aceita `--lingua en`).

## Como usar

Com o Claude Code, abrir este repositório e perguntar. O `CLAUDE.md` diz-lhe como
procurar e citar. Exemplos de perguntas:

- "Uma loja online em Portugal que vende vernizes de unhas para outros países da UE: que
  informação tem de pôr no rótulo segundo o Regulamento dos Cosméticos?"
- "O meu chatbot de apoio ao cliente é um sistema de IA de risco elevado?"
- "Que prazo tem um consumidor para devolver uma compra online, e que excepções há?"

Para actualizar ou acrescentar actos:

```bash
pip install -r requirements.txt
npm install --prefix ferramentas && npx --prefix ferramentas playwright install chromium   # só para o DRE
python3 ferramentas/eurlex.py nucleo                     # actualizar a lista curada
python3 ferramentas/dre.py tudo                          # leis portuguesas de transposição
python3 ferramentas/eurlex.py obter 32019L2161 --area consumidores-e-vendas --curto "Omnibus"
python3 ferramentas/eurlex.py catalogo                   # refazer o catálogo
```

## Fonte e licença — legislação portuguesa

Fonte: Diário da República Eletrónico, serviço público gerido pela Imprensa Nacional-Casa
da Moeda, S. A. (INCM) — https://diariodarepublica.pt. Segundo os avisos legais do DRE, o
acesso universal e gratuito "compreende a possibilidade de impressão, arquivo, pesquisa e
livre acesso ao conteúdo dos atos publicados", e a edição eletrónica do DR faz fé plena;
os textos consolidados são produzidos pela INCM "ainda que sem valor legal".

Direitos: o Código do Direito de Autor (Decreto-Lei n.º 63/85, artigo 8.º, n.º 1) exclui de
protecção os textos das leis; já as "compilações sistemáticas ou anotadas de textos… de
leis" são obras protegidas (artigo 3.º, n.º 1, alínea c)), e o sítio do DRE indica "INCM,
SA — todos os direitos reservados". Os textos consolidados do DRE foram incluídos neste
repositório público por decisão do titular do repositório (2026-10-09), conhecendo esta
questão. Se a INCM o pedir, retiram-se as consolidações e ficam só os textos originais.

**Alterações feitas:** conversão do formato do DRE para Markdown, remoção de ligações
internas, acrescento de metadados (diretivas transpostas, segundo o Cellar).

## Fonte e licença — direito da UE

Fonte: EUR-Lex, © União Europeia, 1998-2026 — https://eur-lex.europa.eu — obtido através
do Cellar (Serviço das Publicações da UE). Segundo o aviso legal do EUR-Lex, os documentos
jurídicos podem ser reutilizados para fins comerciais ou não comerciais (Decisão
2011/833/UE); os textos consolidados e as sínteses estão sob licença
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), e os metadados em CC0.

**Alterações feitas:** conversão de HTML para Markdown, separação do preâmbulo, remoção de
formatação tipográfica (negrito/itálico), tabelas de paginação convertidas em listas, e
acrescento de metadados e de listas (transposição, jurisprudência) obtidas do Cellar.
Os textos consolidados são instrumentos de documentação sem efeito jurídico; fazem fé os
textos publicados no Jornal Oficial da União Europeia.
