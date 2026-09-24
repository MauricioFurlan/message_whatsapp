// Abas + coluna "Resposta" da verificação de respostas (BRAINSTORM_IA.md #7).
//
// O que este teste protege:
//
//  1. **"Não entregou" é categoria própria, nunca "frio".** Misturar as duas
//     faz o cliente descartar contato bom e insistir em número morto — é a
//     mesma armadilha que o CLAUDE.md documenta do lado do envio ("a network
//     outage looks like a bad number").
//  2. **Nada de aba "morno".** Separar morno de quente exige ler o teor da
//     resposta; uma aba que nunca retorna nada é pior que não existir.
//  3. **As abas só aparecem depois da primeira varredura.** Abas zeradas em
//     cima de uma planilha recém-subida só confundem.
//  4. **Quem não respondeu ainda não pode ser contado como respondeu.** Linha
//     sem verificação fica fora de todos os grupos.
//  5. **Ordenar por latência põe o mais rápido no topo**, e quem não tem
//     latência conhecida vai para o fim nas duas direções.
//
// Uso:  node tests/test_varredura_ui.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const raiz = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(raiz, 'static', 'index.html'), 'utf8');
const src = html.split('<script>')[1].split('</script>')[0];

for (const marca of ['id="btn-verificar"', 'id="abas-resposta"', 'id="th-resposta"']) {
    if (!html.includes(marca)) throw new Error(`${marca} não existe em static/index.html`);
}

function stubEl(extra) {
    return Object.assign({
        value: '', innerHTML: '', textContent: '', title: '', style: {}, hidden: false,
        checked: false, disabled: false, dataset: {}, className: '',
        classList: {
            _set: new Set(['hidden']),
            add(c) { this._set.add(c); }, remove(c) { this._set.delete(c); },
            contains(c) { return this._set.has(c); },
            toggle(c, on) { if (on) this._set.add(c); else this._set.delete(c); },
        },
        addEventListener() {}, querySelector: () => stubEl(), querySelectorAll: () => [],
        insertAdjacentHTML() {}, remove() {}, focus() {}, setAttribute() {},
        getAttribute: () => null, removeAttribute() {}, closest: () => null,
        appendChild() {}, removeChild() {}, children: [],
        getBoundingClientRect: () => ({ top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }),
    }, extra || {});
}

// Linhas da tabela: só o dataset importa para o agrupamento.
function linha(ds) {
    return stubEl({ dataset: Object.assign({ enviado: '1', respondeu: '0', entrega: '', latencia: '' }, ds) });
}

let linhas = [];
const abas = stubEl();
const elementos = {
    'abas-resposta': abas,
    'barra-resposta': stubEl(),
    'btn-verificar': stubEl(),
    'btn-start': stubEl(),
    'btn-stop': stubEl({ disabled: true }),
    'contacts-section': stubEl(),
    'contacts-lock-text': stubEl(),
    'status-entrega': stubEl(),
    'verificar-progresso': stubEl(),
    'th-resposta-seta': stubEl(),
    'contacts-tbody': stubEl({
        querySelectorAll: () => linhas,
        appendChild(tr) { const i = linhas.indexOf(tr); if (i >= 0) linhas.splice(i, 1); linhas.push(tr); },
    }),
};

const sandbox = {
    console: { log: () => {}, warn: () => {}, error: () => {} },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: {
        getElementById: (id) => elementos[id] || stubEl(),
        querySelectorAll: (sel) => (sel.includes('contacts-tbody') ? linhas : []),
        addEventListener() {},
        createElement: () => {
            let t = '';
            return {
                get textContent() { return t; },
                set textContent(v) { t = String(v == null ? '' : v); },
                get innerHTML() { return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); },
            };
        },
        createTextNode: (t) => ({ nodeValue: t }), activeElement: null,
    },
    window: { innerWidth: 1280, innerHeight: 800 },
    alert: () => {},
    fetch: () => Promise.resolve({ ok: true, json: () => ({ status: 'ok' }) }),
    EventSource: function () { return { close() {}, addEventListener() {} }; },
    setTimeout, clearTimeout, Promise, Number, String, Math, JSON, Error, Set, isFinite,
};

vm.runInNewContext(src, sandbox);

const { grupoDaLinha, atualizarAbasResposta, filtrarPorResposta, ordenarPorResposta,
        respostaBadgeHtml, formatarLatencia, latenciaPorExtenso,
        escapeHtml, aplicarTravaGeral, atualizarResumoDeEntrega } = sandbox;
for (const [nome, fn] of Object.entries({ grupoDaLinha, atualizarAbasResposta,
        filtrarPorResposta, ordenarPorResposta, respostaBadgeHtml, formatarLatencia,
        latenciaPorExtenso, escapeHtml, aplicarTravaGeral,
        atualizarResumoDeEntrega })) {
    if (typeof fn !== 'function') throw new Error(`${nome} não encontrada em static/index.html`);
}

let falhas = 0;
function checar(titulo, obtido, esperado) {
    const ok = JSON.stringify(obtido) === JSON.stringify(esperado);
    if (!ok) falhas++;
    console.log(`${ok ? 'PASSOU' : 'FALHOU'}  ${titulo}`);
    if (!ok) console.log(`   obtido: ${JSON.stringify(obtido)}   esperado: ${JSON.stringify(esperado)}`);
}

// --- agrupamento -----------------------------------------------------------
checar('respondeu', grupoDaLinha(linha({ respondeu: '1', entrega: 'Respondeu' })), 'respondeu');
checar('entregue sem resposta', grupoDaLinha(linha({ entrega: 'Entregue' })), 'sem_resposta');
checar('lido sem resposta', grupoDaLinha(linha({ entrega: 'Lido' })), 'sem_resposta');
checar('nao entregue é categoria propria, nao "frio"',
    grupoDaLinha(linha({ entrega: 'Não entregue' })), 'nao_entregue');
checar('falha de envio entra em nao entregue',
    grupoDaLinha(linha({ entrega: 'Falhou' })), 'nao_entregue');
checar('enviado mas ainda nao verificado fica de fora dos grupos',
    grupoDaLinha(linha({ entrega: '' })), 'nao_verificado');
checar('quem nunca recebeu nao tem grupo',
    grupoDaLinha(linha({ enviado: '0', entrega: 'Entregue' })), null);

// --- abas ------------------------------------------------------------------
linhas = [linha({ entrega: '' }), linha({ entrega: '' })];
atualizarAbasResposta();
checar('sem verificacao nenhuma, nao mostra abas', abas.innerHTML, '');

linhas = [
    linha({ respondeu: '1', entrega: 'Respondeu', latencia: '600' }),
    linha({ respondeu: '1', entrega: 'Respondeu', latencia: '7200' }),
    linha({ entrega: 'Entregue' }),
    linha({ entrega: 'Não entregue' }),
];
atualizarAbasResposta();
checar('abas aparecem depois da varredura', abas.innerHTML.length > 0, true);
checar('contador de "Respondeu" está certo',
    abas.innerHTML.includes('Respondeu <span class="opacity-70">2</span>'), true);
checar('contador de "Sem resposta" está certo',
    abas.innerHTML.includes('Sem resposta <span class="opacity-70">1</span>'), true);
checar('contador de "Não entregou" está certo',
    abas.innerHTML.includes('Não entregou <span class="opacity-70">1</span>'), true);
checar('não existe aba "morno"', /morno/i.test(abas.innerHTML), false);
checar('não existe aba "frio"', /\bfrio\b/i.test(abas.innerHTML), false);

// --- filtro ----------------------------------------------------------------
filtrarPorResposta('respondeu');
checar('filtro esconde quem não respondeu', linhas.map(l => l.hidden), [false, false, true, true]);
filtrarPorResposta('nao_entregue');
checar('filtro de não entregue isola a base suja', linhas.map(l => l.hidden), [true, true, true, false]);
filtrarPorResposta('todos');
checar('"Todos" mostra tudo de novo', linhas.map(l => l.hidden), [false, false, false, false]);

// --- ordenação -------------------------------------------------------------
linhas = [
    linha({ latencia: '7200' }),
    linha({ latencia: '' }),
    linha({ latencia: '600' }),
];
const marcados = linhas.map((l, i) => (l.dataset.marca = String(i), l));
ordenarPorResposta();
checar('mais rápido primeiro; sem latência vai para o fim',
    linhas.map(l => l.dataset.latencia), ['600', '7200', '']);
ordenarPorResposta();
checar('inverte, mas sem latência continua no fim',
    linhas.map(l => l.dataset.latencia), ['7200', '600', '']);

// --- badge da coluna -------------------------------------------------------
// `enviado: true` em todos: a coluna Resposta so' tem o que dizer sobre quem
// recebeu a mensagem (ver os casos de invalido/pendente logo abaixo).
const badge = (extra) => respostaBadgeHtml(Object.assign({ enviado: true, invalido: false }, extra));

checar('sem verificação mostra travessão',
    /—|&mdash;/.test(badge({ entrega: '', respondeu: false })), true);
checar('respondeu mostra a latência',
    badge({ entrega: 'Respondeu', respondeu: true, latencia_seg: 600 }).includes('10 min'), true);
checar('respondeu sem latência ainda diz "Respondeu"',
    badge({ entrega: 'Respondeu', respondeu: true, latencia_seg: null }).includes('Respondeu'), true);
// Os tiques sao FIEIS ao WhatsApp: cinza tanto para um quanto para dois. O
// que os separa e' a CONTAGEM, nao a cor — e a base suja ("nao entregue" e
// "falhou") continua distinta de lead frio pela aba propria e pelo tooltip,
// que sao o que o cliente usa para agir. So' a falha e' vermelha: nao e' tique,
// e' alerta, e e' o unico estado em que a mensagem nem saiu.
const ehVermelho = (h) => /color:\s*rgb\(220, 38, 38\)/.test(h);
checar('nenhum tique e vermelho (fidelidade ao WhatsApp)',
    ehVermelho(badge({ entrega: 'Não entregue', respondeu: false }))
        || ehVermelho(badge({ entrega: 'Entregue', respondeu: false })), false);
checar('falha continua vermelha (alerta, nao tique)',
    ehVermelho(badge({ entrega: 'Falhou', respondeu: false })), true);
checar('nao entregue e entregue tem a MESMA cor; muda a contagem de tiques',
    /color:\s*rgba\(0, 0, 0, 0\.45\)/.test(badge({ entrega: 'Não entregue', respondeu: false })), true);
// A base suja segue separavel sem depender de cor: aba propria + tooltip.
checar('"não entregou" continua sendo aba própria, não "frio"',
    grupoDaLinha(linha({ entrega: 'Não entregue' })), 'nao_entregue');

// --- contato invalido nunca teve entrega -----------------------------------
// Uma Entrega remanescente numa linha invalida descreve OUTRA mensagem: a de
// antes de ela ser invalidada, ou a de uma campanha anterior. Exibi-la
// afirmaria "a mensagem chegou" sobre uma mensagem que nunca saiu.
const invalido = respostaBadgeHtml({ enviado: false, invalido: true, entrega: 'Lido', respondeu: false });
checar('linha inválida mostra travessão, não o estado de entrega',
    /—|&mdash;/.test(invalido), true);
checar('linha inválida não diz que a mensagem chegou',
    /chegou|Leu/.test(invalido), false);
checar('linha inválida explica por que não há resposta',
    invalido.includes('não foi enviada'), true);
checar('pendente (nem enviado nem inválido) também mostra travessão',
    /—|&mdash;/.test(respostaBadgeHtml({ enviado: false, invalido: false, entrega: '' })), true);

// --- nan do pandas nao pode virar rotulo -----------------------------------
// Celula vazia lida pelo pandas vira o texto "nan" se o backend nao fizer
// fillna. Se isso escapar de novo, ao menos nao pode ser tratado como um
// estado de entrega valido.
checar('"nan" não é tratado como estado conhecido',
    /Leu|Entregue, não leu|chegou no celular/.test(badge({ entrega: 'nan', respondeu: false })), false);

// --- simbolos em vez de palavras ------------------------------------------
// Os tiques sao o vocabulario que o cliente ja le no WhatsApp todo dia. Sao
// SVG, e nao texto "✓✓": o duplo do WhatsApp e' sobreposto, e dois glifos lado
// a lado leem como outra coisa (alem do risco de virar emoji colorido).
const lido = badge({ entrega: 'Lido', respondeu: false });
const entregue = badge({ entrega: 'Entregue', respondeu: false });
const naoEntregue = badge({ entrega: 'Não entregue', respondeu: false });
const falhou = badge({ entrega: 'Falhou', respondeu: false });

const paths = (h) => (h.match(/<path /g) || []).length;
checar('lido e entregue sao tique DUPLO (dois paths)',
    paths(lido) === 2 && paths(entregue) === 2, true);
checar('nao entregue e tique SIMPLES (um path)', paths(naoEntregue), 1);
checar('falhou nao usa tique (seria "chegou, mas deu errado")',
    /<circle/.test(falhou) && paths(falhou) === 1, true);

// Entregue e lido tem o MESMO desenho: so' a cor separa, igual ao WhatsApp.
const desenho = (h) => (h.match(/d="[^"]+"/g) || []).join('|');
checar('lido e entregue tem o mesmo desenho', desenho(lido) === desenho(entregue), true);
checar('e o desenho do tique unico e diferente', desenho(naoEntregue) === desenho(lido), false);
checar('lido e azul (o azul medido no WhatsApp)',
    /color:\s*rgb\(0, 123, 252\)/.test(lido), true);
checar('entregue e cinza', /color:\s*rgba\(0, 0, 0, 0\.45\)/.test(entregue), true);

// REGRESSAO: o Tailwind deste projeto e' PRE-COMPILADO. Uma classe de cor que
// nao esteja no static/tailwind.css gerado nao pinta nada, e o simbolo sai
// PRETO — foi o que aconteceu com `text-blue-500` no tique de lido. Cor de
// tique vai em `style`, que nao depende de build.
for (const [nome, h] of [['lido', lido], ['entregue', entregue],
                         ['nao entregue', naoEntregue], ['falhou', falhou]]) {
    checar('cor de "' + nome + '" nao depende do build do Tailwind',
        /<svg[^>]*style="color:/.test(h) && !/<svg[^>]*class="[^"]*text-\w+-\d+/.test(h), true);
}

// Cor sozinha nao pode ser a unica pista: quem nao distingue azul de cinza
// precisa do texto, e ele tem de estar no tooltip E no aria-label.
checar('cada simbolo tem aria-label',
    [lido, entregue, naoEntregue, falhou].every((h) => /aria-label="[^"]+"/.test(h)), true);
checar('tooltip de lido descreve o simbolo e o significado',
    /tiques azuis/.test(lido) && /leu a mensagem/.test(lido), true);
checar('tooltip de entregue descreve o simbolo e nao afirma que nao leu',
    /tiques cinzas/.test(entregue) && !/não (leu|abriu)/.test(entregue), true);
checar('tooltip de nao entregue explica o tique unico',
    /[Uu]m tique só/.test(naoEntregue), true);

// Resposta continua em TEXTO: nao existe tique para "ele respondeu" — os
// tiques falam da NOSSA mensagem — e o tempo e' o dado que a coluna ordena.
const respondeu = badge({ entrega: 'Respondeu', respondeu: true, latencia_seg: 600 });
checar('resposta continua em texto, com o tempo', respondeu.includes('10 min'), true);
checar('resposta nao vira tique', /<svg/.test(respondeu), false);

// --- acentuacao do texto que o usuario le ----------------------------------
// Reclamacao de campo: "o nao ta sem o a com til". Os textos visiveis sao
// portugues de verdade, mesmo com o codigo em volta evitando acento.
for (const [nome, html] of [['lido', lido], ['entregue', entregue],
                            ['não entregue', badge({ entrega: 'Não entregue', respondeu: false })]]) {
    checar('sem "nao" sem acento no texto de ' + nome, /nao/.test(html), false);
}

// --- formatação de latência ------------------------------------------------
checar('minutos', formatarLatencia(600), '10 min');
checar('horas', formatarLatencia(7200), '2 h');
checar('dias', formatarLatencia(172800), '2 dias');
checar('desconhecida vira vazio', formatarLatencia(''), '');
checar('negativa vira vazio (horário impreciso, não viagem no tempo)', formatarLatencia(-5), '');
// Zero e' resposta legitima: "no mesmo minuto do envio". Arredondar para
// "1 min" afirmaria uma precisao que o horario da linha ("13:17", sem
// segundos) nao tem — e e' justamente o lead mais quente da lista.
checar('mesmo minuto vira "< 1 min"', formatarLatencia(0), '< 1 min');
checar('meio minuto tambem', formatarLatencia(30), '< 1 min');
checar('um minuto cheio ja e "1 min"', formatarLatencia(60), '1 min');
// A celula tem 80px e whitespace-nowrap; "menos de 1 min" foi MEDIDO em 85,5px
// contra 72px de caixa util. A forma por extenso vive no tooltip.
checar('rotulo curto cabe na coluna', formatarLatencia(0).length <= 8, true);
checar('tooltip usa a forma por extenso', latenciaPorExtenso(0), 'menos de um minuto');
checar('acima de um minuto o tooltip repete o curto', latenciaPorExtenso(600), '10 min');
checar('sem latencia nao ha texto no tooltip', latenciaPorExtenso(''), '');

// A celula inteira, para o caso de campo de 12/09/2026: envio 13:17:09,
// resposta no mesmo minuto. Antes isto mostrava so' a palavra "Respondeu" —
// justamente para o lead mais quente — e mandava a linha para o fim da
// ordenacao por latencia.
{
    const html = respostaBadgeHtml({
        invalido: false, enviado: true, entrega: 'Respondeu',
        respondeu: true, latencia_seg: 0,
    });
    const texto = html.replace(/<[^>]+>/g, '').trim();
    const tooltip = /title="([^"]+)"/.exec(html)[1];
    checar('resposta imediata mostra o tempo, nao "Respondeu"', texto, '&lt; 1 min');
    checar('tooltip explica por extenso', tooltip, 'Respondeu em menos de um minuto.');
}

// ---- o tooltip traz o TEMPO, e so' o tempo ----
// O teor da ultima mensagem chegou a aparecer aqui e foi tirado: a varredura
// nao reconsulta quem ja esta `Respondeu=Sim`, entao o texto gravado e' o da
// PRIMEIRA leitura e pode estar velho. O tempo nao muda; o teor pode.
{
    const html = respostaBadgeHtml({
        invalido: false, enviado: true, entrega: 'Respondeu', respondeu: true,
        latencia_seg: 600, resposta_texto: 'Hummm',
    });
    const title = /title="([^"]*)"/.exec(html)[1];
    checar('tooltip traz so o tempo', title, 'Respondeu em 10 min.');
    checar('o teor nao vaza para a tela', html.indexOf('Hummm'), -1);
}

// `escapeHtml` tem de escapar ASPAS, e nao so' o que o `innerHTML` escapa:
// quase todo uso dela e' dentro de `title="..."`, e `pessoa`/`motivo` vem de
// uma planilha que nem sempre foi digitada por quem roda o programa.
{
    const html = respostaBadgeHtml({
        invalido: false, enviado: true, entrega: 'Nao entregue', respondeu: false,
        motivo: 'ola " onmouseover=alert(1) x="',
    });
    checar('nenhum atributo novo nasceu',
        / onmouseover=/.test(html.replace(/title="[^"]*"/g, '')), false);
    checar('aspa dupla escapada', escapeHtml('a"b'), 'a&quot;b');
    checar('aspa simples escapada', escapeHtml("a'b"), 'a&#39;b');
}

// --- trava durante a varredura ---------------------------------------------
// A varredura segura o mesmo chrome_profile/ do envio e reescreve a mesma
// planilha: enquanto ela roda, a tela inteira fica indisponivel. A excecao e'
// o Parar — sem ele o usuario fica preso numa operacao de minutos, sem saida
// que nao seja matar o processo.
aplicarTravaGeral(true, 'Edicao bloqueada durante a verificacao de respostas');
checar('varrendo: Iniciar Envio desabilitado', elementos['btn-start'].disabled, true);
checar('varrendo: Verificar respostas desabilitado', elementos['btn-verificar'].disabled, true);
checar('varrendo: Parar continua ATIVO (unica saida do fluxo)',
    elementos['btn-stop'].disabled, false);
checar('varrendo: contatos travados',
    elementos['contacts-section'].classList.contains('contacts-locked'), true);
checar('varrendo: o banner diz que e a verificacao, nao o envio',
    elementos['contacts-lock-text'].textContent, 'Edicao bloqueada durante a verificacao de respostas');

aplicarTravaGeral(false);
checar('destravado: Iniciar Envio volta', elementos['btn-start'].disabled, false);
checar('destravado: Verificar respostas volta', elementos['btn-verificar'].disabled, false);
checar('destravado: Parar desabilitado (nada rodando)', elementos['btn-stop'].disabled, true);
checar('destravado: contatos liberados',
    elementos['contacts-section'].classList.contains('contacts-locked'), false);

// O botao que dispara a varredura mora em Controles, junto de Iniciar/Parar —
// nao ao lado da tabela, onde parecia um filtro de tela.
const controles = html.split('<!-- Controles -->')[1].split('</section>')[0];
checar('botao "Verificar respostas" esta na secao Controles',
    controles.includes('id="btn-verificar"'), true);
checar('sem icone de lupa no botao', /&#128269;|🔍/.test(controles), false);

// --- tooltips dos tres botoes de Controles ---------------------------------
// O usuario final e' leigo: o tooltip diz o que acontece na pratica e o que
// ele precisa (ou nao precisa) fazer, sem citar navegador, planilha ou
// qualquer mecanismo interno.
const tagDoBotao = (id) => {
    const re = new RegExp('<button[^>]*id="' + id + '"[^>]*>');
    const m = re.exec(html);
    return m ? m[0] : '';
};
for (const id of ['btn-start', 'btn-stop', 'btn-verificar']) {
    const titulo = /title="([^"]+)"/.exec(tagDoBotao(id));
    checar(id + ': tem tooltip explicativo', !!titulo, true);
    if (!titulo) continue;
    checar(id + ': tooltip nao usa jargao tecnico',
        /Selenium|Chrome|planilha|xlsx|SSE|backend|thread/i.test(titulo[1]), false);
    checar(id + ': tooltip esta acentuado', /[à-ü]/.test(titulo[1]), true);
}

// --- resumo de entrega no painel Status ------------------------------------
// Os mesmos simbolos da coluna Resposta, com a contagem. A fonte e' a TABELA,
// e nao um contador proprio: dois contadores independentes divergem na
// primeira linha que alguem editar, e ai o usuario nao sabe em qual acreditar.
const resumo = elementos['status-entrega'];
linhas = [
    linha({ respondeu: '1', entrega: 'Respondeu' }),
    linha({ entrega: 'Lido' }),
    linha({ entrega: 'Lido' }),
    linha({ entrega: 'Entregue' }),
    linha({ entrega: 'Entregue' }),
    linha({ entrega: 'Entregue' }),
    linha({ entrega: 'Não entregue' }),
    linha({ entrega: 'Falhou' }),
    // Nao enviado e invalido nao entram: nunca tiveram entrega.
    linha({ enviado: '0', entrega: 'Lido' }),
];
atualizarResumoDeEntrega();
const numeros = (resumo.innerHTML.match(/>(\d+)<\/span>/g) || []).map((x) => x.replace(/\D/g, ''));
checar('conta responderam, lidos, entregues e nao entregues',
    numeros, ['1', '2', '3', '2']);
checar('falhou entra junto de "nao entregue" (as duas sao base suja)',
    numeros[3], '2');
checar('quem nao recebeu fica de fora da contagem',
    resumo.innerHTML.includes('>4<'), false);
checar('usa os mesmos simbolos da coluna', (resumo.innerHTML.match(/<svg/g) || []).length, 4);
checar('resumo visivel quando ha o que resumir', resumo.classList.contains('hidden'), false);

// Sem verificacao nenhuma a faixa some — uma fileira de zeros so' ocuparia espaco.
linhas = [linha({ entrega: '' }), linha({ entrega: '' })];
atualizarResumoDeEntrega();
checar('sem verificação, o resumo some', resumo.classList.contains('hidden'), true);
checar('e fica vazio', resumo.innerHTML, '');

console.log(falhas === 0 ? '\nTodos os testes passaram.' : `\n${falhas} teste(s) falharam.`);
process.exit(falhas === 0 ? 0 : 1);
