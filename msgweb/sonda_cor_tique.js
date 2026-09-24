/**
 * Sonda v4 — a COR do tique, que e' o que separa "entregue" de "lido".
 *
 * O CASO (08/09/2026)
 *   Mensagem entregue, tique duplo CINZA, e a coluna dizia "Leu". O nome do
 *   icone (`wds-ic-read`) parece ser o mesmo nos dois estados; o que muda na
 *   tela e' a cor. O app agora so' afirma "Leu" com o azul — e esta sonda
 *   confirma qual e' o azul de verdade nesta maquina/tema.
 *
 * COMO USAR
 *   Chrome (o mesmo que a automacao abriu) -> F12 -> Console -> cola tudo.
 *
 *   1) Foto de agora, com o veredito de cada linha:
 *        __cores()
 *
 *   2) Para pegar a TRANSICAO cinza -> azul (que e' a prova):
 *        __vigiar("99422")      // trecho do numero, ou o nome
 *      ...e peca para a pessoa ABRIR a conversa. O vigia grava cada cor nova
 *      por 120s. Depois:
 *        copy(__transicoes)
 *
 * O QUE EU PRECISO VER
 *   - a cor do tique duplo CINZA (entregue, nao lido)
 *   - a cor do tique duplo AZUL  (lido)
 *   - se o `icone` e' o mesmo nos dois (a hipotese) ou muda
 *
 *   Com isso eu ajusto o limiar em `cor_de_leitura()` para os valores reais
 *   em vez do que estimei (azul ~ rgb(83,189,235), cinza ~ rgb(134,150,160)).
 *
 * PRIVACIDADE
 *   Nenhum texto de mensagem sai. Digitos viram "#". Sai cor, nome de icone e
 *   estrutura — nada mais.
 */
(() => {
  const LINHAS = '#pane-side [role="listitem"], #pane-side [role="row"]';
  const SEL = {
    titulo: '[data-testid="cell-frame-title"]',
    status: '[data-testid="last-msg-status"]',
    midia: '[data-testid="chat-msg-symbol"]',
    nao_lidas: '[data-testid="icon-unread-count"]',
  };

  const mask = (t) => (t || "").replace(/\d/g, "#");
  const digitos = (t) => (t || "").replace(/\D/g, "");
  const txt = (linha, sel) => {
    const el = linha.querySelector(sel);
    return el ? el.textContent || "" : "";
  };

  /** O <svg> do tique de status — o mesmo que o app usa. */
  const svgDeStatus = (raiz) => {
    if (!raiz) return null;
    for (const t of raiz.querySelectorAll("svg > title")) {
      if (t.closest(SEL.midia)) continue;
      return t.parentElement;
    }
    for (const el of raiz.querySelectorAll("[data-icon]")) {
      if (el.closest(SEL.midia)) continue;
      return el;
    }
    return null;
  };

  /** A MESMA regra do linha_conversa.py — para o veredito bater com o app. */
  const ehAzul = (cor) => {
    const m = /rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/.exec(cor || "");
    if (!m) return false;
    const [r, g, b] = [+m[1], +m[2], +m[3]];
    return b >= 150 && b - r >= 60;
  };

  const ler = (linha, i) => {
    const status = linha.querySelector(SEL.status);
    const svg = svgDeStatus(status);
    let cor = "", corPai = "", classes = "";
    if (svg) {
      try {
        cor = getComputedStyle(svg).color || "";
        classes = (svg.getAttribute("class") || "").slice(0, 60);
        if (svg.parentElement) corPai = getComputedStyle(svg.parentElement).color || "";
      } catch (e) {}
    }
    const titleEl = svg ? svg.querySelector("title") : null;
    const icone = titleEl
      ? (titleEl.textContent || "").trim()
      : (svg ? svg.getAttribute("data-icon") || "" : "");
    const naoLidas = Number(digitos(txt(linha, SEL.nao_lidas))) || 0;
    return {
      i,
      titulo: mask(txt(linha, SEL.titulo)),
      icone,
      cor,
      cor_do_pai: corPai,
      classes_svg: classes,
      nao_lidas: naoLidas,
      // O que o app conclui HOJE com esta linha:
      veredito: naoLidas > 0
        ? "respondeu"
        : !svg
          ? "respondeu (sem icone)"
          : /message-fail/i.test(icone)
            ? "falhou"
            : /wds-ic-read/i.test(icone)
              ? (ehAzul(cor) ? "LIDO (azul)" : "ENTREGUE (nao azul)")
              : /wds-ic-delivered/i.test(icone)
                ? "entregue"
                : "nao entregue",
    };
  };

  window.__cores = () => {
    const linhas = [...document.querySelectorAll(LINHAS)];
    if (!linhas.length) return console.warn("Nenhuma linha. Seletor mudou:", LINHAS);
    const saida = linhas.slice(0, 20).map(ler);
    console.table(saida.map(({ i, icone, cor, nao_lidas, veredito }) =>
      ({ i, icone, cor, nao_lidas, veredito })));
    window.__resultado = saida;
    console.log("Rode  copy(__resultado)  para copiar tudo (com classes e cor do pai).");
    return saida;
  };

  window.__transicoes = [];
  window.__vigiar = (trecho, segundos = 120) => {
    const achar = () =>
      [...document.querySelectorAll(LINHAS)].find((l) => {
        const t = txt(l, SEL.titulo);
        return t.includes(trecho) || digitos(t).includes(digitos(trecho));
      });
    if (!achar()) return console.warn(`Nada casa com "${trecho}". Rode __cores() para ver a lista.`);

    window.__transicoes = [];
    let anterior = "";
    const t0 = Date.now();
    console.log(`Vigiando "${trecho}" por ${segundos}s. Peca para a pessoa ABRIR a conversa.`);

    const timer = setInterval(() => {
      const linha = achar();
      if (linha) {
        const r = ler(linha, -1);
        const chave = r.icone + "|" + r.cor + "|" + r.nao_lidas;
        if (chave !== anterior) {
          anterior = chave;
          const evento = Object.assign({ t: ((Date.now() - t0) / 1000).toFixed(1) + "s" }, r);
          window.__transicoes.push(evento);
          console.log("MUDOU:", evento.t, evento.icone, evento.cor, "->", evento.veredito);
        }
      }
      if (Date.now() - t0 > segundos * 1000) {
        clearInterval(timer);
        console.log(`Fim. ${window.__transicoes.length} estado(s). Rode  copy(__transicoes)`);
      }
    }, 500);
    return "vigiando...";
  };

  console.log('Sonda de cor carregada.  __cores()   ou   __vigiar("99422")');
})();
