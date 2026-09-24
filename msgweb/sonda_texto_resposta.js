/**
 * Sonda v5 — ONDE mora o TEXTO da resposta dele.
 *
 * A PERGUNTA (12/09/2026)
 *   Para classificar quente/morno/frio sem IA (BRAINSTORM_IA.md #7 -> #5) o
 *   unico dado que falta e' o TEOR da resposta. O `linha_conversa.py` ja
 *   extrai um campo `ultima_mensagem`, mas ele vem do `title` do
 *   `[data-testid="last-msg-status"]` — um elemento que existe para carregar
 *   o TIQUE da NOSSA mensagem.
 *
 *   Hipotese a testar: numa linha cuja ultima mensagem e' DELE nao ha tique,
 *   logo pode nao haver `last-msg-status` nenhum, e `ultima_mensagem` sai ""
 *   exatamente nos contatos que interessam.
 *
 *   O candidato de reserva e' `linha_previa` ([data-testid="cell-frame-secondary"]),
 *   que ja esta no `PADRAO` do seletores.py e hoje nao e' lido por ninguem.
 *
 * O QUE PRECISO SABER
 *   1. Nas linhas "ultima mensagem e' DELE", qual candidato tem texto SEMPRE?
 *   2. O texto vem inteiro ou truncado? (o `?` pode estar depois do corte)
 *   3. O `?` sobrevive? (e' o marcador de "quente" da regra proposta)
 *
 * COMO USAR
 *   Chrome logado no WhatsApp Web -> F12 -> Console -> cola tudo.
 *     __sondaTexto()        // imprime a tabela + o veredito
 *     copy(__sonda5)        // JSON para colar aqui
 *
 * PRIVACIDADE
 *   Todo digito vira "#". As amostras de texto sao truncadas em 30 caracteres
 *   — o suficiente para ver se e' mensagem de verdade e se tem "?" — e os
 *   TAMANHOS sao reportados como numero, nao como texto. Confira o JSON antes
 *   de enviar.
 */
(() => {
  const LINHAS = '#pane-side [role="listitem"], #pane-side [role="row"]';
  const SEL = {
    titulo: '[data-testid="cell-frame-title"]',
    status: '[data-testid="last-msg-status"]',
    previa: '[data-testid="cell-frame-secondary"]',
    midia: '[data-testid="chat-msg-symbol"]',
    nao_lidas: '[data-testid="icon-unread-count"]',
  };
  const MAX_AMOSTRA = 30;

  // Marcas bidi invisiveis que o WhatsApp poe em volta do texto.
  const BIDI = /[‎‏؜‪-‮⁦-⁩]/g;
  const limpar = (t) => (t || "").replace(BIDI, "").trim();
  const mask = (t) => limpar(t).replace(/\d/g, "#");
  const amostra = (t) => {
    const m = mask(t);
    return m.length > MAX_AMOSTRA ? m.slice(0, MAX_AMOSTRA) + "…" : m;
  };

  // Mesma regra do linha_conversa.py: icone de STATUS e' o que esta no
  // last-msg-status e FORA do simbolo de midia (figurinha que ELE mandou
  // mora no mesmo lugar e seria lida como tique nosso).
  const iconesDeStatus = (raiz) => {
    if (!raiz) return [];
    const nomes = [];
    raiz.querySelectorAll("svg > title").forEach((t) => {
      if (t.closest(SEL.midia)) return;
      const n = limpar(t.textContent);
      if (n) nomes.push(n);
    });
    raiz.querySelectorAll("[data-icon]").forEach((el) => {
      if (el.closest(SEL.midia)) return;
      const n = limpar(el.getAttribute("data-icon"));
      if (n) nomes.push(n);
    });
    return nomes;
  };

  const contarNaoLidas = (linha) => {
    const el = linha.querySelector(SEL.nao_lidas);
    if (!el) return 0;
    const d = (el.textContent || "").replace(/\D/g, "");
    return d ? parseInt(d, 10) : 0;
  };

  const campo = (el, attr) => {
    if (!el) return { existe: false, len: 0, amostra: "", tem_interrog: false };
    const bruto = attr ? el.getAttribute(attr) : el.textContent;
    const t = limpar(bruto);
    return {
      existe: true,
      len: t.length,
      amostra: amostra(t),
      tem_interrog: t.includes("?"),
      // "..." no fim denuncia truncagem feita pelo proprio WhatsApp
      truncado_visual: /[…]$|\.\.\.$/.test(t),
    };
  };

  window.__sondaTexto = () => {
    const linhas = [...document.querySelectorAll(LINHAS)];
    const out = linhas.map((linha, i) => {
      const status = linha.querySelector(SEL.status);
      const previa = linha.querySelector(SEL.previa);
      const icones = iconesDeStatus(status);
      const naoLidas = contarNaoLidas(linha);
      // Ultima mensagem e' DELE quando nao ha tique nenhum, ou quando ha
      // badge de nao-lidas (que vence tudo — ver decidir_estado()).
      const deles = naoLidas > 0 || icones.length === 0;
      return {
        indice: i,
        titulo: amostra(linha.querySelector(SEL.titulo)?.textContent),
        ultima_msg_e_dele: deles,
        nao_lidas: naoLidas,
        icones: icones,
        // O que o linha_conversa.py le HOJE:
        status_title: campo(status, "title"),
        // Candidatos alternativos:
        status_texto: campo(status, null),
        previa_texto: campo(previa, null),
        previa_title: campo(previa, "title"),
        linha_title: campo(linha, "title"),
      };
    });

    const deles = out.filter((l) => l.ultima_msg_e_dele);
    const cobertura = (chave) => {
      if (!deles.length) return null;
      const com = deles.filter((l) => l[chave].existe && l[chave].len > 0).length;
      return `${com}/${deles.length}`;
    };

    const veredito = {
      linhas_renderizadas: out.length,
      linhas_com_ultima_msg_dele: deles.length,
      cobertura_do_texto_nas_linhas_dele: {
        status_title_HOJE: cobertura("status_title"),
        status_texto: cobertura("status_texto"),
        previa_texto: cobertura("previa_texto"),
        previa_title: cobertura("previa_title"),
        linha_title: cobertura("linha_title"),
      },
      tamanho_medio: {
        status_title: media(deles.map((l) => l.status_title.len)),
        previa_texto: media(deles.map((l) => l.previa_texto.len)),
      },
      com_interrogacao: {
        status_title: deles.filter((l) => l.status_title.tem_interrog).length,
        previa_texto: deles.filter((l) => l.previa_texto.tem_interrog).length,
      },
    };

    window.__sonda5 = { veredito, linhas: out };
    console.log("=== VEREDITO ===");
    console.log(JSON.stringify(veredito, null, 2));
    console.log("=== LINHAS (dele primeiro) ===");
    console.table(
      [...deles, ...out.filter((l) => !l.ultima_msg_e_dele)].map((l) => ({
        i: l.indice,
        dele: l.ultima_msg_e_dele,
        nlidas: l.nao_lidas,
        status_title: l.status_title.existe ? l.status_title.len : "-",
        previa: l.previa_texto.existe ? l.previa_texto.len : "-",
        amostra_previa: l.previa_texto.amostra,
      }))
    );
    return window.__sonda5;
  };

  function media(ns) {
    const v = ns.filter((n) => n > 0);
    return v.length ? Math.round(v.reduce((a, b) => a + b, 0) / v.length) : 0;
  }

  console.log("Sonda v5 carregada. Rode: __sondaTexto()");
  return "ok";
})();
