# Índice — por onde começar

Gerado por `python3 ferramentas/indexar.py` em 2026-10-10. 64324 actos da UE (64273 em vigor, 7 em vigor por confirmar no Cellar, 44 futuros), 86 no corpus curado, leis portuguesas de transposição em `legislacao-pt/`.

## Para gastar poucos tokens

1. **Não abras ficheiros inteiros.** Um regulamento pode ter 50 000+ tokens; um artigo tem 200–2 000.
2. **Encontra o acto**: `python3 ferramentas/procurar.py actos <palavras>` (nome popular, título, temas, EuroVoc) ou `rg -i '<palavra>' indice/actos.tsv | cut -f1,2,3,13`.
3. **Vê o sumário do acto**: `python3 ferramentas/procurar.py artigos <CELEX>` (artigos, epígrafes, linhas e tokens de cada um).
4. **Lê só o artigo**: `python3 ferramentas/procurar.py ler <CELEX> 6` (ou `sed -n '<ini>,<fim>p' <ficheiro>` com as linhas do sumário).
5. **Não sabes o acto?** Pesquisa no texto: `python3 ferramentas/procurar.py texto "<pergunta>"` (devolve os artigos mais relevantes de toda a legislação; constrói o índice local na 1.ª vez).
6. **Empresa em Portugal + diretiva**: `python3 ferramentas/procurar.py pt <CELEX da diretiva>` dá a lei portuguesa que a transpõe.

## Índices

| Ficheiro | Para quê |
|---|---|
| `indice/actos.tsv` | Uma linha por acto: `celex`, `nome` popular, `titulo`, `tipo`, `data`, `estado`, `texto`, `temas`, `repertorio`, `eurovoc`, `artigos`, `tokens`, `ficheiro`, `curado`, `leis_pt`. |
| `indice/temas/<cap>.md` | Actos por área do repertório (capítulos abaixo). |
| `indice/eurovoc.tsv` | Descritor temático EuroVoc → actos. Bom para sinónimos e temas transversais. |
| `indice/artigos/…/*.tsv` | Sumário de cada acto: unidade (artigo/anexo), epígrafe, linhas, tokens. Pesquisar epígrafes em toda a legislação: `rg -i 'direito de retratação' indice/artigos`. |
| `corpus/INDICE.md` | Os actos curados (com considerandos, sínteses, transposição, jurisprudência). |
| `legislacao-pt/INDICE.md` | Leis portuguesas por diretiva. |
| `catalogo/legislacao-em-vigor.tsv` | Catálogo completo com ELI e ligações. |

## Áreas (repertório oficial do EUR-Lex)

- [`01` Questões gerais, institucionais e financeiras](indice/temas/01.md) — 2823 actos
- [`02` União aduaneira e livre circulação das mercadorias](indice/temas/02.md) — 2394 actos
- [`03` Agricultura](indice/temas/03.md) — 8280 actos
- [`04` Pescas](indice/temas/04.md) — 1217 actos
- [`05` Livre circulação dos trabalhadores e política social](indice/temas/05.md) — 1153 actos
- [`06` Direito de estabelecimento e liberdade de prestação de serviços](indice/temas/06.md) — 1335 actos
- [`07` Política dos transportes](indice/temas/07.md) — 1771 actos
- [`08` Política da concorrência](indice/temas/08.md) — 11619 actos
- [`09` Fiscalidade](indice/temas/09.md) — 506 actos
- [`10` Política económica e monetária e livre circulação de capitais](indice/temas/10.md) — 1341 actos
- [`11` Relações externas](indice/temas/11.md) — 14836 actos
- [`12` Energia](indice/temas/12.md) — 708 actos
- [`13` Política industrial e mercado interno](indice/temas/13.md) — 4513 actos
- [`14` Política regional e coordenação dos instrumentos estruturais](indice/temas/14.md) — 555 actos
- [`15` Ambiente, consumidores e proteção da saúde](indice/temas/15.md) — 5598 actos
- [`16` Ciência, Informação, Educação e Cultura](indice/temas/16.md) — 766 actos
- [`17` Legislação aplicável às empresas](indice/temas/17.md) — 221 actos
- [`18` Política Externa e de Segurança Comum](indice/temas/18.md) — 3873 actos
- [`19` Espaço de liberdade, segurança e justiça](indice/temas/19.md) — 1457 actos
- [`20` Europa dos cidadãos](indice/temas/20.md) — 156 actos

## Actos curados mais pedidos

- `31993L0013` Cláusulas abusivas — `corpus/consumidores-e-vendas/31993L0013-clausulas-abusivas.md`
- `31998L0006` Indicação dos preços — `corpus/consumidores-e-vendas/31998L0006-indicacao-dos-precos.md`
- `32005L0029` Práticas comerciais desleais — `corpus/consumidores-e-vendas/32005L0029-praticas-comerciais-desleais.md`
- `32006L0114` Publicidade enganosa e comparativa — `corpus/consumidores-e-vendas/32006L0114-publicidade-enganosa-e-comparativa.md`
- `32011L0083` Direitos dos consumidores — `corpus/consumidores-e-vendas/32011L0083-direitos-dos-consumidores.md`
- `32013L0011` Resolução alternativa de litígios de consumo — `corpus/consumidores-e-vendas/32013L0011-resolucao-alternativa-de-litigios-de-consumo.md`
- `32019L0770` Conteúdos e serviços digitais — `corpus/consumidores-e-vendas/32019L0770-conteudos-e-servicos-digitais.md`
- `32019L0771` Venda de bens (garantias) — `corpus/consumidores-e-vendas/32019L0771-venda-de-bens-garantias.md`
- `32020L1828` Ações coletivas — `corpus/consumidores-e-vendas/32020L1828-acoes-coletivas.md`
- `32023L2225` Crédito aos consumidores — `corpus/consumidores-e-vendas/32023L2225-credito-aos-consumidores.md`
- `32024L1799` Direito à reparação — `corpus/consumidores-e-vendas/32024L1799-direito-a-reparacao.md`
- `32006R1896` Procedimento europeu de injunção de pagamento — `corpus/contratos-e-litigios/32006R1896-procedimento-europeu-de-injuncao-de-pagamento.md`
- `32007R0861` Processo europeu de ações de pequeno montante — `corpus/contratos-e-litigios/32007R0861-processo-europeu-de-acoes-de-pequeno-montante.md`
- `32008R0593` Roma I (lei aplicável aos contratos) — `corpus/contratos-e-litigios/32008R0593-roma-i-lei-aplicavel-aos-contratos.md`
- `32011L0007` Atrasos de pagamento nas transações comerciais — `corpus/contratos-e-litigios/32011L0007-atrasos-de-pagamento-nas-transacoes-comerciais.md`
- `32012R1215` Bruxelas I-A (competência judiciária) — `corpus/contratos-e-litigios/32012R1215-bruxelas-i-a-competencia-judiciaria.md`
- `32002L0058` Diretiva ePrivacy (cookies e comunicações eletrónicas) — `corpus/dados-e-privacidade/32002L0058-diretiva-eprivacy-cookies-e-comunicacoes-eletronicas.md`
- `32016R0679` RGPD — `corpus/dados-e-privacidade/32016R0679-rgpd.md`
- `32018R1807` Livre circulação de dados não pessoais — `corpus/dados-e-privacidade/32018R1807-livre-circulacao-de-dados-nao-pessoais.md`
- `32022R0868` Regulamento Governação de Dados — `corpus/dados-e-privacidade/32022R0868-regulamento-governacao-de-dados.md`
- `32023R2854` Regulamento dos Dados (Data Act) — `corpus/dados-e-privacidade/32023R2854-regulamento-dos-dados-data-act.md`
- `32000L0031` Diretiva Comércio Eletrónico — `corpus/digital-plataformas-e-ia/32000L0031-diretiva-comercio-eletronico.md`
- `32010L0013` Diretiva Serviços de Comunicação Social Audiovisual — `corpus/digital-plataformas-e-ia/32010L0013-diretiva-servicos-de-comunicacao-social-audiovisual.md`
- `32014R0910` eIDAS (identificação e assinaturas eletrónicas) — `corpus/digital-plataformas-e-ia/32014R0910-eidas-identificacao-e-assinaturas-eletronicas.md`
- `32018R0302` Regulamento Bloqueio Geográfico — `corpus/digital-plataformas-e-ia/32018R0302-regulamento-bloqueio-geografico.md`
- `32019L0882` Ato Europeu da Acessibilidade — `corpus/digital-plataformas-e-ia/32019L0882-ato-europeu-da-acessibilidade.md`
- `32019R1150` Regulamento Plataformas-Empresas (P2B) — `corpus/digital-plataformas-e-ia/32019R1150-regulamento-plataformas-empresas-p2b.md`
- `32022L2555` Diretiva NIS 2 — `corpus/digital-plataformas-e-ia/32022L2555-diretiva-nis-2.md`
- `32022R1925` Regulamento dos Mercados Digitais (DMA) — `corpus/digital-plataformas-e-ia/32022R1925-regulamento-dos-mercados-digitais-dma.md`
- `32022R2065` Regulamento dos Serviços Digitais (DSA) — `corpus/digital-plataformas-e-ia/32022R2065-regulamento-dos-servicos-digitais-dsa.md`
- `32024R1689` Regulamento IA — `corpus/digital-plataformas-e-ia/32024R1689-regulamento-ia.md`
- `32024R2847` Regulamento Ciber-Resiliência — `corpus/digital-plataformas-e-ia/32024R2847-regulamento-ciber-resiliencia.md`
- `32013L0034` Diretiva Contabilística — `corpus/empresas-e-financas/32013L0034-diretiva-contabilistica.md`
- `32014L0024` Contratos públicos — `corpus/empresas-e-financas/32014L0024-contratos-publicos.md`
- `32014R0651` Regulamento Geral de Isenção por Categoria (GBER) — `corpus/empresas-e-financas/32014R0651-regulamento-geral-de-isencao-por-categoria-gber.md`
- `32015L0849` Branqueamento de capitais (diretiva) — `corpus/empresas-e-financas/32015L0849-branqueamento-de-capitais-diretiva.md`
- `32015L2366` Serviços de pagamento (PSD2) — `corpus/empresas-e-financas/32015L2366-servicos-de-pagamento-psd2.md`
- `32017L1132` Direito das sociedades — `corpus/empresas-e-financas/32017L1132-direito-das-sociedades.md`
- `32022R0720` Acordos verticais (distribuição) — `corpus/empresas-e-financas/32022R0720-acordos-verticais-distribuicao.md`
- `32022R2554` Resiliência operacional digital (DORA) — `corpus/empresas-e-financas/32022R2554-resiliencia-operacional-digital-dora.md`
- `32023R1114` Criptoativos (MiCA) — `corpus/empresas-e-financas/32023R1114-criptoativos-mica.md`
- `32023R2831` Auxílios de minimis — `corpus/empresas-e-financas/32023R2831-auxilios-de-minimis.md`
- `32024R1624` Branqueamento de capitais (regulamento) — `corpus/empresas-e-financas/32024R1624-branqueamento-de-capitais-regulamento.md`
- `32006L0112` Diretiva IVA — `corpus/iva-alfandegas-e-fiscalidade/32006L0112-diretiva-iva.md`
- `32010R0904` Cooperação administrativa IVA (OSS) — `corpus/iva-alfandegas-e-fiscalidade/32010R0904-cooperacao-administrativa-iva-oss.md`
- `32011L0016` Cooperação administrativa fiscal (DAC, inclui DAC7 plataformas) — `corpus/iva-alfandegas-e-fiscalidade/32011L0016-cooperacao-administrativa-fiscal-dac-inclui-dac7-plataformas.md`
- `32011R0282` Regulamento de Execução IVA — `corpus/iva-alfandegas-e-fiscalidade/32011R0282-regulamento-de-execucao-iva.md`
- `32013R0952` Código Aduaneiro da União — `corpus/iva-alfandegas-e-fiscalidade/32013R0952-codigo-aduaneiro-da-uniao.md`
- `32014L0055` Faturação eletrónica nos contratos públicos — `corpus/iva-alfandegas-e-fiscalidade/32014L0055-faturacao-eletronica-nos-contratos-publicos.md`
- `31985L0374` Responsabilidade por produtos defeituosos (antiga) — `corpus/produtos-e-cosmeticos/31985L0374-responsabilidade-por-produtos-defeituosos-antiga.md`
- `32006R1907` REACH — `corpus/produtos-e-cosmeticos/32006R1907-reach.md`
- `32008D0768` Quadro comum de comercialização de produtos (marcação CE) — `corpus/produtos-e-cosmeticos/32008D0768-quadro-comum-de-comercializacao-de-produtos-marcacao-ce.md`
- `32008R0765` Acreditação e fiscalização do mercado — `corpus/produtos-e-cosmeticos/32008R0765-acreditacao-e-fiscalizacao-do-mercado.md`
- `32008R1272` CLP (classificação e rotulagem de químicos) — `corpus/produtos-e-cosmeticos/32008R1272-clp-classificacao-e-rotulagem-de-quimicos.md`
- `32009R1223` Regulamento Cosméticos — `corpus/produtos-e-cosmeticos/32009R1223-regulamento-cosmeticos.md`
- `32011L0065` RoHS (substâncias perigosas em EEE) — `corpus/produtos-e-cosmeticos/32011L0065-rohs-substancias-perigosas-em-eee.md`
- `32012L0019` REEE (resíduos de equipamentos elétricos) — `corpus/produtos-e-cosmeticos/32012L0019-reee-residuos-de-equipamentos-eletricos.md`
- `32013D0674` Orientações relatório de segurança dos cosméticos — `corpus/produtos-e-cosmeticos/32013D0674-orientacoes-relatorio-de-seguranca-dos-cosmeticos.md`
- `32013R0655` Alegações de produtos cosméticos — `corpus/produtos-e-cosmeticos/32013R0655-alegacoes-de-produtos-cosmeticos.md`
- `32014L0030` Compatibilidade eletromagnética — `corpus/produtos-e-cosmeticos/32014L0030-compatibilidade-eletromagnetica.md`
- `32014L0035` Baixa tensão — `corpus/produtos-e-cosmeticos/32014L0035-baixa-tensao.md`
- `32019R1020` Fiscalização do mercado — `corpus/produtos-e-cosmeticos/32019R1020-fiscalizacao-do-mercado.md`
- `32023R0988` Regulamento Segurança Geral dos Produtos (GPSR) — `corpus/produtos-e-cosmeticos/32023R0988-regulamento-seguranca-geral-dos-produtos-gpsr.md`
- `32023R1542` Regulamento Baterias — `corpus/produtos-e-cosmeticos/32023R1542-regulamento-baterias.md`
- `32024L2853` Responsabilidade por produtos defeituosos (nova) — `corpus/produtos-e-cosmeticos/32024L2853-responsabilidade-por-produtos-defeituosos-nova.md`
- `32024R1781` Regulamento Conceção Ecológica (ESPR) — `corpus/produtos-e-cosmeticos/32024R1781-regulamento-concecao-ecologica-espr.md`
- `32025R0040` Regulamento Embalagens (PPWR) — `corpus/produtos-e-cosmeticos/32025R0040-regulamento-embalagens-ppwr.md`
- `32001L0029` Direitos de autor na sociedade da informação — `corpus/propriedade-intelectual/32001L0029-direitos-de-autor-na-sociedade-da-informacao.md`
- `32009L0024` Proteção jurídica de programas de computador — `corpus/propriedade-intelectual/32009L0024-protecao-juridica-de-programas-de-computador.md`
- `32016L0943` Segredos comerciais — `corpus/propriedade-intelectual/32016L0943-segredos-comerciais.md`
- `32017R1001` Marca da União Europeia — `corpus/propriedade-intelectual/32017R1001-marca-da-uniao-europeia.md`
- `32019L0790` Direitos de autor no mercado único digital — `corpus/propriedade-intelectual/32019L0790-direitos-de-autor-no-mercado-unico-digital.md`
- `31989L0391` Segurança e saúde no trabalho (diretiva-quadro) — `corpus/trabalho/31989L0391-seguranca-e-saude-no-trabalho-diretiva-quadro.md`
- `31996L0071` Destacamento de trabalhadores — `corpus/trabalho/31996L0071-destacamento-de-trabalhadores.md`
- `32000L0078` Igualdade de tratamento no emprego — `corpus/trabalho/32000L0078-igualdade-de-tratamento-no-emprego.md`
- `32003L0088` Tempo de trabalho — `corpus/trabalho/32003L0088-tempo-de-trabalho.md`
- `32006L0054` Igualdade de género no emprego — `corpus/trabalho/32006L0054-igualdade-de-genero-no-emprego.md`
- `32019L1152` Condições de trabalho transparentes e previsíveis — `corpus/trabalho/32019L1152-condicoes-de-trabalho-transparentes-e-previsiveis.md`
- `32019L1158` Conciliação vida profissional e familiar — `corpus/trabalho/32019L1158-conciliacao-vida-profissional-e-familiar.md`
- `32019L1937` Proteção de denunciantes — `corpus/trabalho/32019L1937-protecao-de-denunciantes.md`
- `32022L2041` Salários mínimos adequados — `corpus/trabalho/32022L2041-salarios-minimos-adequados.md`
- `32023L0970` Transparência salarial — `corpus/trabalho/32023L0970-transparencia-salarial.md`
- `32024L2831` Trabalho em plataformas digitais — `corpus/trabalho/32024L2831-trabalho-em-plataformas-digitais.md`
- `12016E/TXT` TFUE — `corpus/tratados/12016E_TXT-tfue.md`
- `12016M/TXT` TUE — `corpus/tratados/12016M_TXT-tue.md`
- `12016P/TXT` Carta dos Direitos Fundamentais — `corpus/tratados/12016P_TXT-carta-dos-direitos-fundamentais.md`

Tipos de acto: Decisão 17501; Regulamento 16282; Decisão sobre concentração 9512; Acordo internacional 9132; Tratado 7393; Diretiva 1306; Outro acto 868; Acto complementar 710; Recomendação 545; Parecer 382; Acto interno de instituição ou órgão 154; Orientação (BCE) 130; Ação ou posição comum (PESC) 118; Resolução 104; Orçamento 73; Decisão-quadro 54; Decisão CECA 52; Recomendação CECA 8.
