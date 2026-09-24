/**
 * Sonda v2 — os tiques da NOSSA ultima mensagem no #pane-side.
 *
 * O QUE JA SE SABE (sondas de 06/09/2026)
 *   - ancoras estaveis: cell-frame-title / -primary-detail / -secondary,
 *     last-msg-status, icon-unread-count, chat-msg-symbol, list-item-N
 *   - numero nao salvo aparece em cell-frame-title como "+55 19 99594-7333":
 *     so os digitos ja casam com clean_number()
 *   - "wds-ic-read" = vv azul (lido), confirmado em duas amostras
 *   - o title do last-msg-status vem cercado de marcas bidi invisiveis
 *     (U+202A / U+202C) — limpar antes de usar
 *
 * O QUE FALTA
 *   os estados intermediarios: v (enviado) e vv (entregue, cinza). Sao
 *   transicoes de segundos — foto nao pega, por isso o modo VIGIA.
 *
 * COMO USAR
 *   Sources -> Snippets -> cole -> Ctrl+Enter. Isso ja imprime a foto atual.
 *
 *   Para capturar as transicoes:
 *     __vigiar("99594")        // trecho do numero, ou do nome
 *   ...e MANDE a mensagem para esse contato. O vigia grava cada estado novo
 *   do icone por 90s. Depois:
 *     copy(__vigia)
 *
 *   Dica: para pegar o "v" solitario e o "vv" cinza, mande para um contato
 *   com o celular desligado / sem internet, ou observe nos 2-3s iniciais.
 *
 * PRIVACIDADE
 *   Nenhum texto de mensagem sai: title/aria-label viram "<len:N>" e digitos
 *   viram "#". Sai estrutura e cor, nada mais.
 */
(() => {
  const mask = (t) => (t || "").replace(/\d/g, "#");
  const lenOnly = (t) => (t ? `<len:${t.length}>` : "");
  const soDigitos = (t) => (t || "").replace(/\D/g, "");

  const atributos = (el) =>
    Object.fromEntries(
      [...el.attributes].map((a) => [
        a.name,
        a.name === "title" || a.name === "aria-label" ? lenOnly(a.value) : mask(a.value),
      ])
    );

  const cor = (el) => {
    try {
      const s = getComputedStyle(el);
      const svg = el.querySelector("svg");
      return { color: s.color, color_svg: svg ? getComputedStyle(svg).color : null };
    } catch (e) {
      return null;
    }
  };

  const LINHAS = '#pane-side [role="listitem"], #pane-side [role="row"]';

  /** O elemento de status da previa: o que NAO e o span de texto. */
  const iconesDaPrevia = (linha) => {
    const sec = linha.querySelector('[data-testid="cell-frame-secondary"]');
    if (!sec) return [];
    return [...sec.querySelectorAll("*")].filter((el) => {
      const temTexto = [...el.childNodes].some(
        (n) => n.nodeType === Node.TEXT_NODE && n.textContent.trim()
      );
      return (
        el.tagName.toLowerCase() === "svg" ||
        el.hasAttribute("data-icon") ||
        /ic-/.test(el.getAttribute("data-testid") || "") ||
        /ic-/.test((el.className && (el.className.baseVal ?? el.className) || "").toString()) ||
        (!temTexto && el.querySelector("svg,path"))
      );
    });
  };

  /** Assinatura estavel de um estado de icone — e o que o vigia compara. */
  const assinatura = (el) => ({
    tag: el.tagName.toLowerCase(),
    atributos: atributos(el),
    cor: cor(el),
    // e aqui que o nome do icone vaza quando o sprite nao renderiza
    texto_proprio: mask(el.textContent || "").slice(0, 30),
    html: el.outerHTML.replace(/\d/g, "#").slice(0, 400),
  });

  const nomeDoIcone = (el) =>
    el.getAttribute("data-icon") ||
    el.getAttribute("data-testid") ||
    ((el.textContent || "").match(/[\w-]*ic-[\w-]+/) || [])[0] ||
    "?";

  const dumpLinha = (linha, i) => {
    const t = linha.querySelector('[data-testid="cell-frame-title"]');
    const sec = linha.querySelector('[data-testid="cell-frame-secondary"]');
    return {
      indice: i,
      list_item: linha.getAttribute("data-testid"),
      titulo_mascarado: mask(t ? t.textContent : ""),
      titulo_e_numero: soDigitos(t ? t.textContent : "").length >= 10,
      horario: mask(
        linha.querySelector('[data-testid="cell-frame-primary-detail"]')
          ? linha.querySelector('[data-testid="cell-frame-primary-detail"]').textContent
          : ""
      ),
      badge_nao_lidas: linha.querySelector('[data-testid="icon-unread-count"]')
        ? linha.querySelector('[data-testid="icon-unread-count"]').textContent
        : null,
      previa_texto_cru: mask(sec ? sec.textContent : "").slice(0, 40),
      icones: iconesDaPrevia(linha).map(assinatura),
    };
  };

  // ---------- Foto atual ----------
  const linhas = [...document.querySelectorAll(LINHAS)];
  const comIcone = linhas.map(dumpLinha).filter((l) => l.icones.length);

  const inventario = {};
  linhas.forEach((linha) =>
    iconesDaPrevia(linha).forEach((el) => {
      const k = nomeDoIcone(el);
      inventario[k] = (inventario[k] || 0) + 1;
    })
  );

  window.__tiques = {
    versao_sonda: 2,
    total_linhas: linhas.length,
    linhas_com_icone: comIcone.length,
    inventario_de_icones: inventario,
    amostras: comIcone.slice(0, 10),
  };

  // ---------- Modo vigia ----------
  window.__vigiar = (filtro, segundos) => {
    segundos = segundos || 90;

    const alvo = () =>
      [...document.querySelectorAll(LINHAS)].find((l) => {
        const el = l.querySelector('[data-testid="cell-frame-title"]');
        const t = el ? el.textContent : "";
        const d = soDigitos(filtro);
        return t.includes(filtro) || (d && soDigitos(t).includes(d));
      });

    if (!alvo()) {
      console.warn(`VIGIA: nenhuma linha casa com "${filtro}". A conversa esta visivel na lista?`);
      return;
    }

    const estados = [];
    let ultima = null;
    const t0 = Date.now();

    // Disponivel DESDE JA: copy(__vigia) funciona a qualquer momento, nao so
    // no fim da janela. O objeto e o mesmo, vai sendo preenchido.
    window.__vigia = { filtro: "<oculto>", duracao_s: segundos, encerrado: false, estados };

    console.log(`VIGIA armado em "${filtro}" por ${segundos}s. Mande a mensagem agora.`);
    console.log("Pode dar copy(__vigia) a qualquer momento — nao precisa esperar o fim.");

    const timer = setInterval(() => {
      const linha = alvo();
      if (linha) {
        const ics = iconesDaPrevia(linha);
        const sig = JSON.stringify(ics.map(assinatura));
        if (sig !== ultima) {
          ultima = sig;
          estados.push({
            t_ms: Date.now() - t0,
            n_icones: ics.length,
            icones: ics.map(assinatura),
          });
          console.log(
            `  [${((Date.now() - t0) / 1000).toFixed(1)}s] estado novo:`,
            ics.map(nomeDoIcone).join(", ") || "(nenhum icone)"
          );
        }
      }
      if (Date.now() - t0 > segundos * 1000) {
        clearInterval(timer);
        window.__vigia.encerrado = true;
        console.log("=== VIGIA encerrado ===");
        console.log(JSON.stringify(window.__vigia, null, 2));
        console.log("Use copy(__vigia) para copiar.");
      }
    }, 250);
  };

  console.log("=== SONDA v2 (foto) ===");
  console.log(JSON.stringify(window.__tiques, null, 2));
  console.log('Para as transicoes: __vigiar("99594") e mande a mensagem. Depois copy(__vigia).');
  return window.__tiques;
})();
