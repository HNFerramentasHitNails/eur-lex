// Recolhe do Diário da República (diariodarepublica.pt) os dados de diplomas, tal como a
// própria página os pede ao servidor, e guarda-os em .cache/dre/<chave>.json.
//
// O site é uma aplicação JavaScript (OutSystems): o texto não vem no HTML, vem em pedidos
// internos ("screenservices") que exigem sessão e token. Em vez de imitar esses pedidos,
// abre-se a página num Chromium sem interface e regista-se a resposta que ela recebe.
//
// Uso: node ferramentas/dre.js <tarefas.json> [paralelo=2]
//   tarefas.json: [{"chave": "...", "detalhe": "<url>", "consolidada": "<url ou vazio>"}]

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const RAIZ = path.resolve(__dirname, '..');
const CACHE = path.join(RAIZ, '.cache', 'dre');
const UA = 'eur-lex-corpus/1.0 (+https://github.com/HNFerramentasHitNails/eur-lex)';
const PAUSA_MS = 1500;

const ALVOS = {
  detalhe: /Conteudo_Detalhe\/DataActionGetAllConteudoDetalheData/,
  menu: /WB_LeftMenuForGeneralDetailScreens\/DataActionGetAllLeftMenuData/,
  consolidada: /LegCons_Detalhe\/DataActionGetData$/,
  consolidadaInfo: /LegCons_Detalhe\/DataActionGetDiplomaFragByIdAndApplicationSetting/,
};

async function abrir(context, url, nomes) {
  const page = await context.newPage();
  const recolhido = {};
  page.on('response', async (r) => {
    for (const nome of nomes) {
      if (ALVOS[nome].test(r.url()) && r.status() === 200) {
        try { recolhido[nome] = JSON.parse(await r.text()).data; } catch (e) { /* resposta incompleta */ }
      }
    }
  });
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 120000 });
    const limite = Date.now() + 120000;
    while (nomes.some((n) => !(n in recolhido)) && Date.now() < limite) {
      // Consolidação registada mas não publicada: o DRE mostra uma página de erro.
      if (recolhido.consolidadaInfo && recolhido.consolidadaInfo.IsPublished === false) break;
      await page.waitForTimeout(500);
    }
    return { url: page.url(), ...recolhido };
  } finally {
    await page.close();
  }
}

async function tratar(context, tarefa) {
  let t = tarefa;
  const destino = path.join(CACHE, `${t.chave}.json`);
  if (fs.existsSync(destino)) return 'cache';
  const res = { chave: t.chave, obtido_em: new Date().toISOString().slice(0, 10) };
  if (t.detalhe) {
    res.detalhe = await abrir(context, t.detalhe, ['detalhe', 'menu']);
    await new Promise((r) => setTimeout(r, PAUSA_MS));
  }
  if (t.consolidada) {
    res.consolidada = await abrir(context, t.consolidada, ['consolidada', 'consolidadaInfo']);
    await new Promise((r) => setTimeout(r, PAUSA_MS));
    if (res.consolidada.consolidadaInfo && res.consolidada.consolidadaInfo.IsPublished === false) {
      res.consolidada_nao_publicada = t.consolidada;  // fica o texto original
      delete res.consolidada;
      t = { ...t, consolidada: '' };
    }
  }
  const okDet = !t.detalhe || (res.detalhe && res.detalhe.detalhe);
  const okCons = !t.consolidada || (res.consolidada && res.consolidada.consolidada);
  if (!okDet || !okCons) return 'incompleto';
  fs.writeFileSync(destino, JSON.stringify(res));
  return 'ok';
}

(async () => {
  const tarefas = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const paralelo = parseInt(process.argv[3] || '2', 10);
  fs.mkdirSync(CACHE, { recursive: true });
  const browser = await chromium.launch();
  const context = await browser.newContext({ userAgent: UA, locale: 'pt-PT' });
  let i = 0;
  async function trabalhador() {
    while (i < tarefas.length) {
      const t = tarefas[i++];
      let estado;
      for (let n = 0; n < 3; n++) {
        try { estado = await tratar(context, t); } catch (e) { estado = 'erro: ' + e.message.split('\n')[0]; }
        if (estado === 'ok' || estado === 'cache') break;
        await new Promise((r) => setTimeout(r, 5000 * (n + 1)));
      }
      console.log(`${estado}\t${t.chave}`);
    }
  }
  await Promise.all(Array.from({ length: paralelo }, trabalhador));
  await browser.close();
})();
