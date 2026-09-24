/**
 * Sonda do #pane-side — levantamento de seletores para a feature de
 * classificacao de contatos (BRAINSTORM_IA.md, #7 / #7b / #7c).
 *
 * COMO USAR
 *   1. Abra o WhatsApp Web logado na conta da campanha (pode ser o
 *      chrome_profile/ do app, ou qualquer Chrome logado).
 *   2. F12 -> Console.
 *   3. Cole este arquivo inteiro e de Enter.
 *   4. Copie o JSON impresso (ou use copy(__sonda) para ir direto pro
 *      clipboard).
 *
 * PRIVACIDADE
 *   A sonda NAO exporta numero nem texto de mensagem: todo digito vira "#"
 *   e todo texto e truncado em 20 caracteres. O que sai daqui e ESTRUTURA
 *   (data-icon, aria-label, role, title, cor computada), nao conteudo.
 *   Confira o JSON antes de enviar, mesmo assim.
 *
 * O QUE ELA RESPONDE
 *   - como identificar a linha de um contato
 *   - como ler o tique (v / vv / vv azul) da nossa ultima mensagem
 *   - como ler o badge de nao-lidas
 *   - como ler o horario da linha
 *   - se a ultima mensagem e nossa ou dele
 *   - qual o seletor da caixa de busca
 */
(() => {
  const MAX_LINHAS = 8;

  const mask = (t) => (t || "").trim().replace(/\d/g, "#").slice(0, 20);

  const cor = (el) => {
    try {
      const c = getComputedStyle(el).color;
      const svg = el.querySelector("svg, path");
      const c2 = svg ? getComputedStyle(svg).color : null;
      const fill = svg ? svg.getAttribute("fill") : null;
      return { color: c, color_svg: c2, fill };
    } catch (e) {
      return null;
    }
  };

  const pane = document.querySelector("#pane-side");
  if (!pane) {
    console.error("SONDA: #pane-side nao encontrado. A lista de conversas esta visivel?");
    return;
  }

  const seletorLinha = '#pane-side [role="listitem"], #pane-side [role="row"]';
  const linhas = [...document.querySelectorAll(seletorLinha)];

  const dumpLinha = (linha) => {
    // Todo elemento com atributo estavel (os que sobrevivem a mudanca de CSS)
    const ancoras = [...linha.querySelectorAll("[data-icon],[aria-label],[title],[role],[data-testid]")]
      .map((el) => ({
        tag: el.tagName.toLowerCase(),
        data_icon: el.getAttribute("data-icon"),
        aria_label: mask(el.getAttribute("aria-label")),
        title: mask(el.getAttribute("title")),
        role: el.getAttribute("role"),
        data_testid: el.getAttribute("data-testid"),
        texto: mask(el.textContent),
        cor: el.hasAttribute("data-icon") ? cor(el) : undefined,
      }))
      .filter((o) => o.data_icon || o.aria_label || o.title || o.data_testid || o.role);

    // Folhas de texto na ordem em que aparecem (nome, previa, horario...)
    const textos = [...linha.querySelectorAll("span,div")]
      .filter((el) => el.children.length === 0 && el.textContent.trim())
      .map((el) => mask(el.textContent));

    return {
      aria_label_linha: mask(linha.getAttribute("aria-label")),
      ancoras,
      textos: [...new Set(textos)].slice(0, 12),
      html_amostra: linha.outerHTML.replace(/\d/g, "#").slice(0, 900),
    };
  };

  // Caixa de busca: precisa dela pra varredura pos-envio (#7)
  const buscaCandidatos = [
    ...document.querySelectorAll(
      '[contenteditable="true"][role="textbox"],[data-testid*="search"],[aria-label*="esquis"],[aria-label*="earch"]'
    ),
  ].map((el) => ({
    tag: el.tagName.toLowerCase(),
    role: el.getAttribute("role"),
    aria_label: mask(el.getAttribute("aria-label")),
    data_testid: el.getAttribute("data-testid"),
    contenteditable: el.getAttribute("contenteditable"),
    dentro_do_pane: !!el.closest("#pane-side"),
  }));

  // Inventario de todos os data-icon visiveis na lista: e daqui que saem os
  // nomes dos tiques (msg-check / msg-dblcheck / status-time / ...).
  const inventarioIcones = {};
  [...pane.querySelectorAll("[data-icon]")].forEach((el) => {
    const k = el.getAttribute("data-icon");
    if (!inventarioIcones[k]) {
      inventarioIcones[k] = { ocorrencias: 0, exemplo_cor: cor(el), aria: mask(el.getAttribute("aria-label")) };
    }
    inventarioIcones[k].ocorrencias++;
  });

  const out = {
    versao_sonda: 1,
    url: location.origin,
    seletor_linha_usado: seletorLinha,
    total_linhas_renderizadas: linhas.length,
    aviso_virtualizacao:
      "So conta o que esta na viewport — #pane-side e virtualizado. Role a lista e rode de novo pra comparar.",
    inventario_data_icon: inventarioIcones,
    caixa_de_busca: buscaCandidatos,
    linhas: linhas.slice(0, MAX_LINHAS).map(dumpLinha),
  };

  window.__sonda = out;
  console.log("=== SONDA #pane-side ===");
  console.log(JSON.stringify(out, null, 2));
  console.log("Pronto. Use copy(__sonda) para copiar pro clipboard.");
  return out;
})();
