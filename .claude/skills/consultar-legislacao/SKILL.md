---
name: consultar-legislacao
description: Responder a perguntas sobre o que a lei da UE (e as leis portuguesas que a transpõem) exige a um negócio, produto, app, bot, contrato, tratamento de dados, trabalhador ou consumidor, usando este repositório de forma dirigida e com poucos tokens. Usar sempre que a pergunta for "posso…", "tenho de…", "que regras…", "que prazo…", "que coima…", "é obrigatório…", "como cumprir…", ou mencionar RGPD, IA, consumidores, IVA, cosméticos, produtos, embalagens, trabalho, plataformas, marcas, etc.
---

# Consultar a legislação de forma dirigida

Objectivo: chegar ao artigo certo lendo o mínimo. Um regulamento inteiro pode custar 50 000+
tokens; o artigo que responde custa normalmente 200–2 000. **Nunca abras um ficheiro de
`ue/`, `corpus/` ou `legislacao-pt/` inteiro** — usa `ferramentas/procurar.py`.

Responde em português de Portugal.

## 1. Perceber a pergunta (sem gastar tokens)

Identifica, a partir do que o utilizador já disse:

- **Quem**: empresa que vende a consumidores (B2C), só a empresas (B2B), consumidor,
  trabalhador/empregador, plataforma online, entidade pública.
- **O quê**: produto (que tipo: cosmético, eléctrico, brinquedo, químico, alimento…), serviço
  digital, dados pessoais, sistema de IA, contrato, fatura/IVA, contratação de pessoas, marca.
- **Onde**: só Portugal, vendas para outros Estados-Membros, fora da UE.
- **Quando**: agora, ou uma data futura (há regras já publicadas que só se aplicam depois).
- **O que quer saber**: se pode, o que tem de fazer, prazos, informação obrigatória, sanções,
  definições.

## 2. Perguntar só o que muda a resposta

Se faltar um elemento que **muda a lei aplicável**, pergunta antes de pesquisar — **no máximo
3 perguntas, numa só mensagem, com opções** (usa a ferramenta de perguntas se existir).
Se o utilizador não estiver disponível ou a pergunta já for clara, não perguntes: assume e
escreve a suposição na resposta ("Assumi que vende a consumidores; se for só a empresas…").

Perguntas decisivas por tema (escolhe só as que faltam):

| Tema | Perguntas que mudam a resposta |
|---|---|
| Vendas / consumidores | Vende a consumidores ou só a empresas? Online/à distância, fora do estabelecimento, ou em loja? Bens, conteúdos digitais ou serviços? |
| Dados pessoais | Trata dados de pessoas na UE? Decide os fins (responsável) ou trata por conta de outro (subcontratante)? Há dados sensíveis (saúde, biométricos) ou de crianças? Usa cookies/rastreio? |
| Inteligência artificial | Desenvolve o sistema (prestador) ou usa-o (responsável pela implantação)? Interage com pessoas ou gera conteúdo? É usado para decisões sobre emprego, crédito, educação, acesso a serviços, biometria? |
| Produtos | Que produto exactamente? É colocado no mercado da UE pela primeira vez por si (fabricante/importador) ou revende? Tem electrónica/bateria? Que embalagem? |
| Cosméticos | Que tipo (unhas, cabelo, pele…)? Uso profissional ou pelo consumidor? Que substâncias/alegações? |
| IVA / faturação | Vende bens ou serviços? A consumidores de outros Estados-Membros? Que valor anual de vendas à distância? Importa de fora da UE? |
| Trabalho | Contrato de trabalho, prestação de serviços ou plataforma? Quantos trabalhadores? Que matéria (horário, férias, salário, despedimento, igualdade)? |
| Plataformas / serviços digitais | Aloja conteúdos de terceiros? Liga vendedores a consumidores (mercado em linha)? Dimensão (micro/pequena empresa ou muito grande)? |

## 3. Encontrar o acto

```bash
python3 ferramentas/procurar.py actos <palavras>        # nome popular, número, título, temas, EuroVoc
```

Atalhos para os temas mais comuns (actos curados, com considerandos, transposição e
jurisprudência em `corpus/`):

| Área | Actos (nome `CELEX`) |
|---|---|
| Dados pessoais e privacidade | RGPD `32016R0679`; ePrivacy/cookies `32002L0058`; Data Act `32023R2854`; Governação de Dados `32022R0868` |
| Digital, plataformas, IA, ciber | Regulamento IA `32024R1689`; DSA `32022R2065`; DMA `32022R1925`; Comércio Eletrónico `32000L0031`; P2B `32019R1150`; Bloqueio geográfico `32018R0302`; eIDAS `32014R0910`; NIS 2 `32022L2555`; Ciber-Resiliência `32024R2847`; Acessibilidade `32019L0882` |
| Consumidores e vendas | Direitos dos consumidores `32011L0083`; Práticas comerciais desleais `32005L0029`; Cláusulas abusivas `31993L0013`; Indicação de preços `31998L0006`; Conteúdos digitais `32019L0770`; Venda de bens/garantias `32019L0771`; Direito à reparação `32024L1799`; Crédito aos consumidores `32023L2225` |
| Contratos e litígios | Roma I `32008R0593`; Bruxelas I-A `32012R1215`; Pequeno montante `32007R0861`; Injunção europeia `32006R1896`; Atrasos de pagamento `32011L0007` |
| Produtos, cosméticos, químicos | GPSR `32023R0988`; Responsabilidade por produtos `32024L2853` / `31985L0374`; Cosméticos `32009R1223`; Alegações cosméticas `32013R0655`; CLP `32008R1272`; REACH `32006R1907`; Baixa tensão `32014L0035`; CEM `32014L0030`; RoHS `32011L0065`; REEE `32012L0019`; Baterias `32023R1542`; Embalagens `32025R0040`; Conceção ecológica `32024R1781` |
| IVA e alfândegas | Diretiva IVA `32006L0112`; Regulamento de Execução IVA `32011R0282`; OSS `32010R0904`; DAC/DAC7 `32011L0016`; Código Aduaneiro `32013R0952` |
| Empresas e finanças | Contabilística `32013L0034`; Sociedades `32017L1132`; GBER (apoios) `32014R0651`; de minimis `32023R2831`; Acordos verticais `32022R0720`; Contratos públicos `32014L0024`; PSD2 `32015L2366`; MiCA `32023R1114`; DORA `32022R2554`; Branqueamento `32015L0849` / `32024R1624` |
| Trabalho | Tempo de trabalho `32003L0088`; Condições transparentes `32019L1152`; Conciliação `32019L1158`; Transparência salarial `32023L0970`; Denunciantes `32019L1937`; Destacamento `31996L0071`; Plataformas digitais `32024L2831` |
| Propriedade intelectual | Marca UE `32017R1001`; Segredos comerciais `32016L0943`; Direitos de autor `32019L0790` / `32001L0029`; Software `32009L0024` |

Fora destes, `procurar.py actos` cobre os 64 mil actos em vigor (`ue/`), e `INDICE.md` tem
as áreas do repertório oficial (`indice/temas/<cap>.md`).

## 4. Ir ao artigo

```bash
python3 ferramentas/procurar.py artigos <CELEX> [palavra]   # sumário: artigo — epígrafe [linhas, ≈tokens]
python3 ferramentas/procurar.py ler <CELEX> <n.º>           # só esse artigo (ex.: 6, 4-A, "anexo III")
python3 ferramentas/procurar.py texto "<pergunta>" --n 8    # quando não sabes o acto nem o artigo
```

Ordem de leitura habitual: artigo das **definições** (2.º/3.º/4.º) → artigo que responde →
**excepções** e **âmbito** → considerandos só se a interpretação for duvidosa
(`corpus/<area>/<…>.considerandos.md`, procura o número com `rg`).

**Orçamento**: tenta responder lendo menos de ~15 000 tokens. Vê o `≈tokens` no sumário antes
de ler um anexo.

## 5. Diretivas → lei portuguesa

Se a regra vem de uma **diretiva** e a pergunta é sobre uma empresa em Portugal:

```bash
python3 ferramentas/procurar.py pt <CELEX da diretiva>
python3 ferramentas/procurar.py artigos <chave-da-lei-pt> <palavra>   # ex.: decreto-lei-24-2014
python3 ferramentas/procurar.py ler decreto-lei-24-2014 10
```

Cita a lei portuguesa como regra aplicável e a diretiva como origem. Se o ficheiro diz
`original (DRE)`, avisa que alterações posteriores não estão incorporadas.

## 6. Responder

1. **Resposta curta primeiro** (sim/não/o que fazer/prazo).
2. **Fundamento** com citação exacta: acto, artigo, n.º, alínea, versão (`versao_aplicavel_desde`
   ou `versao_consolidada_de`) e ficheiro:linhas.
3. **Suposições** que fizeste e o que mudaria se fossem outras.
4. **O que não verificaste** (lei nacional não incluída, orientações das autoridades, versões
   futuras, rectificações) — ver "Limites" no `CLAUDE.md`. Se o ficheiro tiver
   `estado: futuro` ou `estado: em vigor (por confirmar)`, di-lo e indica a `nota_estado`.
5. Se houver coimas, contratos, declarações fiscais ou colocação de produtos no mercado: diz que
   é uma leitura do texto legal e que o caso concreto deve ser validado por um profissional.

Se não encontraste a regra, diz "não encontrei" e como procuraste (comandos e palavras usadas).
