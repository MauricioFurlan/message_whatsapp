/**
 * Sonda v3 — por que uma linha de quem RESPONDEU foi lida como "Lido".
 *
 * O CASO (08/09/2026)
 *   O contato respondeu, a linha mostra o badge verde de 1 nao-lida, e a
 *   varredura gravou "Lido / a mensagem chegou mas ele nao respondeu".
 *
 *   A regra de `linha_conversa.py` decide por AUSENCIA: sem icone de status,
 *   a ultima mensagem e' dele. Para dar "Lido" o extrator precisa ter achado
 *   um `wds-ic-read` DENTRO de `[data-testid="last-msg-status"]` naquela
 *   linha. Esta sonda mostra se ele realmente estava la, e de onde veio.
 *
 * COMO USAR
 *   Chrome (o mesmo que a automacao abriu) -> F12 -> Console -> cola tudo.
 *   Depois:
 *       __sonda("99422")      // um trecho do numero, ou o nome do contato
 *
 *   Se nao achar nada, rode `__sonda()` sem argumento: lista as 15 primeiras
 *   linhas com o veredito de cada uma, para voce localizar a certa.
 *
 * O QUE OLHAR NA SAIDA
 *   - `veredito`      : o que o app concluiria HOJE (o bug esta aqui se
 *                       disser "lido" numa conversa que tem resposta)
 *   - `nao_lidas`     : > 0 e' prova independente de que chegou mensagem dele
 *   - `icones_status` : os nomes crus. Se vier `wds-ic-read` junto com um
 *                       badge de nao-lida, a lista esta mostrando as duas
 *                       coisas ao mesmo tempo e o icone sozinho nao serve.
 *   - `status_html`   : a estrutura do no de status, sem texto nenhum. E' o
 *                       que diz se pegamos o elemento certo.
 *
 * PRIVACIDADE
 *   Nenhum texto de mensagem sai. Digitos viram "#", textos viram "<len:N>".
 *   Sai estrutura, nomes de icone e contadores — nada mais. Pode colar a
 *   saida inteira aqui no chat.
 */
(() => {
  const LINHAS = '#pane-side [role="listitem"], #pane-side [role="row"]';
  const SEL = {
    titulo: '[data-testid="cell-frame-title"]',
    horario: '[data-testid="cell-frame-primary-detail"]',
    status: '[data-testid="last-msg-status"]',
    midia: '[data-testid="chat-msg-symbol"]',
    nao_lidas: '[data-testid="icon-unread-count"]',
  };

  const mask = (t) => (t || "").replace(/\d/g, "#");
  const lenOnly = (t) => (t ? `<len:${t.length}>` : "");
  const digitos = (t) => (t || "").replace(/\D/g, "");

  /** Esqueleto do no: tags e atributos estruturais, zero texto. */
  const esqueleto = (el, prof = 0) => {
    if (!el || prof > 4) return null;
    const attrs = {};
    for (const a of el.attributes || []) {
      if (a.name === "title" || a.name === "aria-label") attrs[a.name] = lenOnly(a.value);
      else if (a.name === "class") attrs[a.name] = `<${a.value.split(/\s+/).length} classes>`;
      else attrs[a.name] = mask(a.value);
    }
    return {
      tag: el.tagName.toLowerCase(),
      attrs,
      texto: el.tagName.toLowerCase() === "title" ? el.textContent : undefined,
      filhos: [...el.children].map((f) => esqueleto(f, prof + 1)).filter(Boolean),
    };
  };

  /** A MESMA logica do linha_conversa.py, para o veredito bater com o app. */
  const iconesDeStatus = (raiz) => {
    if (!raiz) return [];
    const nomes = [];
    raiz.querySelectorAll("svg > title").forEach((t) => {
      if (t.closest(SEL.midia)) return;
      const n = (t.textContent || "").trim();
      if (n) nomes.push(n);
    });
    raiz.querySelectorAll("[data-icon]").forEach((el) => {
      if (el.closest(SEL.midia)) return;
      const n = (el.getAttribute("data-icon") || "").trim();
      if (n) nomes.push(n);
    });
    return nomes;
  };

  const vereditoDe = (icones, naoLidas) => {
    if (naoLidas > 0) return "respondeu (pelo badge de nao-lidas)";
    if (!icones.length) return "respondeu (nenhum icone)";
    const n = icones.map((i) => i.toLowerCase());
    if (n.some((i) => i.includes("message-fail"))) return "falhou";
    if (n.some((i) => i.includes("wds-ic-read"))) return "lido";
    if (n.some((i) => i.includes("wds-ic-delivered"))) return "entregue";
    return "nao entregue";
  };

  const ler = (linha, i) => {
    const t = (sel) => {
      const el = linha.querySelector(sel);
      return el ? el.textContent || "" : "";
    };
    const status = linha.querySelector(SEL.status);
    const naoLidas = Number(digitos(t(SEL.nao_lidas))) || 0;
    const icones = iconesDeStatus(status);
    return {
      indice: i,
      titulo_mascarado: mask(t(SEL.titulo)),
      titulo_digitos: digitos(t(SEL.titulo)).length,
      horario: t(SEL.horario),
      nao_lidas: naoLidas,
      icones_status: icones,
      status_existe: !!status,
      veredito: vereditoDe(icones, naoLidas),
      // Todos os <title> de svg da LINHA INTEIRA, nao so' os de dentro do
      // status. Se um wds-ic-read aparecer aqui e nao em icones_status, o
      // problema e' de onde estamos procurando.
      titles_da_linha_toda: [...linha.querySelectorAll("svg > title")].map((x) => x.textContent),
      status_html: esqueleto(status),
    };
  };

  window.__sonda = (trecho) => {
    const linhas = [...document.querySelectorAll(LINHAS)];
    if (!linhas.length) {
      console.warn("Nenhuma linha encontrada. O seletor da lista mudou:", LINHAS);
      return;
    }
    if (!trecho) {
      const resumo = linhas.slice(0, 15).map((l, i) => {
        const r = ler(l, i);
        return { i, digitos_no_titulo: r.titulo_digitos, hora: r.horario, nao_lidas: r.nao_lidas, veredito: r.veredito };
      });
      console.table(resumo);
      console.log("Rode __sonda('<trecho do numero ou nome>') para o detalhe de uma linha.");
      return resumo;
    }
    const alvo = linhas
      .map((l, i) => [l, i])
      .filter(([l]) => {
        const el = l.querySelector(SEL.titulo);
        const txt = el ? el.textContent || "" : "";
        return txt.includes(trecho) || digitos(txt).includes(digitos(trecho));
      });
    if (!alvo.length) {
      console.warn(`Nenhuma linha casa com "${trecho}". Rode __sonda() sem argumento para listar.`);
      return;
    }
    const saida = alvo.map(([l, i]) => ler(l, i));
    console.log(JSON.stringify(saida, null, 2));
    window.__resultado = saida;
    console.log('Pronto. Rode  copy(__resultado)  para copiar, e cole no chat.');
    return saida;
  };

  console.log('Sonda carregada. Use: __sonda("99422")   ou   __sonda()  para listar.');
})();
