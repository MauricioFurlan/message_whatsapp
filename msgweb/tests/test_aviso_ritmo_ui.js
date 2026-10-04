// Aviso de ritmo da configuração: não pisca, não some sem explicar, e
// sempre diz quanto tempo o envio deve levar.
//
// Relato (2026-10-04): "50 mensagens em 5 minutos" abria um alerta que sumia
// logo depois. Eram duas checagens: a local (só o piso de 15s) mostrava
// "Ritmo apertado" na hora, e 400ms depois a resposta do /estimate — que
// conta os pendentes REAIS, e a planilha tinha 1 — o apagava sem dizer nada.
// Regra do usuário: o aviso não some e mostra quanto tempo vai levar.
//
// - O servidor é quem decide o aviso; a checagem local só vale quando ele
//   não pode responder (sem planilha, fora do ar).
// - Cada caso em que o envio não sai como pedido tem texto, com o tempo.
//
// Uso:  node tests/test_aviso_ritmo_ui.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const raiz = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(raiz, 'static', 'index.html'), 'utf8');
const src = html.split('<script>')[1].split('</script>')[0];

function classList() {
    return {
        _set: new Set(),
        add(c) { this._set.add(c); },
        remove(c) { this._set.delete(c); },
        toggle(c, on) { if (on === undefined) on = !this._set.has(c); on ? this._set.add(c) : this._set.delete(c); },
        contains(c) { return this._set.has(c); },
    };
}

function stubEl(extra) {
    const el = Object.assign({
        value: '', innerHTML: '', textContent: '', title: '', placeholder: '',
        checked: false, disabled: false, style: {}, files: [], dataset: {},
        _cl: classList(),
        addEventListener() {}, querySelector: () => null,
        querySelectorAll: () => [], insertAdjacentHTML() {}, remove() {}, focus() {},
        closest: () => null, appendChild() {}, removeChild() {}, children: [],
    }, extra || {});
    // className e classList precisam andar juntos, como no DOM.
    Object.defineProperty(el, 'className', {
        get() { return [...el._cl._set].join(' '); },
        set(v) { el._cl._set = new Set(String(v).split(/\s+/).filter(Boolean)); },
    });
    el.classList = el._cl;
    return el;
}

const elementos = {
    'cfg-total-msgs-input': stubEl({ value: '50' }),
    'cfg-tempo': stubEl({ value: '5' }),
    'cfg-estimativa': stubEl(),
    'cfg-aviso-ritmo': stubEl(),
    'cfg-total-msgs-header': stubEl(),
};
elementos['cfg-aviso-ritmo'].className = 'text-xs text-red-500 mt-1 hidden';

let respostaEstimate = null;   // objeto JSON, ou 'falha' para erro de rede
const timers = [];
const chamadas = [];           // [url, opts] de cada fetch ao /estimate
let linhasDaTabela = [];       // o que '#contacts-tbody tr' devolve

const sandbox = {
    console: { log: () => {}, warn: () => {}, error: () => {} },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: {
        getElementById: (id) => elementos[id] || stubEl(),
        addEventListener() {},
        createElement: () => stubEl(),
        querySelectorAll: (sel) => (sel === '#contacts-tbody tr' ? linhasDaTabela : []),
        activeElement: null,
    },
    window: { innerHeight: 800, addEventListener() {} },
    URLSearchParams,
    fetch: (url, opts) => {
        if (String(url).startsWith('/estimate')) {
            chamadas.push([String(url), opts || {}]);
            if (respostaEstimate === 'falha') return Promise.reject(new Error('rede'));
            return Promise.resolve({ ok: true, json: () => Promise.resolve(respostaEstimate) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    },
    EventSource: function () { return { close() {}, addEventListener() {} }; },
    // Timers manuais: o teste decide quando o debounce de 400ms "passa".
    setTimeout: (fn) => { timers.push(fn); return timers.length; },
    clearTimeout: () => {},
    Number, String, Math, JSON, parseInt, RegExp, Promise, Error,
};

vm.runInNewContext(src, sandbox);

const { updateEstimativa, textoAvisoRitmo } = sandbox;
for (const [nome, fn] of Object.entries({ updateEstimativa, textoAvisoRitmo })) {
    if (typeof fn !== 'function') throw new Error(`${nome} não encontrada em static/index.html`);
}

let falhas = 0;
function checar(titulo, obtido, esperado) {
    const ok = JSON.stringify(obtido) === JSON.stringify(esperado);
    if (!ok) falhas++;
    console.log(`${ok ? 'PASSOU' : 'FALHOU'}  ${titulo}`);
    if (!ok) console.log(`   obtido: ${JSON.stringify(obtido)}   esperado: ${JSON.stringify(esperado)}`);
}
function contem(titulo, texto, trecho) {
    const ok = typeof texto === 'string' && texto.includes(trecho);
    if (!ok) falhas++;
    console.log(`${ok ? 'PASSOU' : 'FALHOU'}  ${titulo}`);
    if (!ok) console.log(`   texto: ${JSON.stringify(texto)}   devia conter: ${JSON.stringify(trecho)}`);
}

const aviso = elementos['cfg-aviso-ritmo'];
const visivel = () => !aviso.classList.contains('hidden');

async function rodarDebounce() {
    const pendentes = timers.splice(0);
    for (const fn of pendentes) await fn();
}

(async () => {
    // --- o caso do relato: 50 em 5min, 1 pendente --------------------------
    respostaEstimate = {
        status: 'ok', session_target: 1, pendentes: 1, inviavel: false,
        tempo_total_estimado_seg: 69, tempo_total_estimado_fmt: '1min 9s',
    };
    updateEstimativa();
    checar('antes do servidor responder, nenhum alerta pisca', visivel(), false);
    await rodarDebounce();
    checar('com 1 pendente o aviso aparece e fica', visivel(), true);
    contem('diz quantos pendentes há', aviso.textContent, 'Só há 1 contato pendente');
    contem('diz quantas vão sair, e que não são as pedidas', aviso.textContent, 'será enviada 1 mensagem, não 50');
    contem('diz quanto tempo deve levar', aviso.textContent, '1min 9s');

    // --- tempo que não cabe ------------------------------------------------
    respostaEstimate = {
        status: 'ok', session_target: 50, pendentes: 50, inviavel: true,
        tempo_total_estimado_seg: 4440, tempo_total_estimado_fmt: '1h 14min',
    };
    updateEstimativa();
    await rodarDebounce();
    checar('inviável: aviso visível', visivel(), true);
    checar('inviável: em vermelho', aviso.classList.contains('text-red-600'), true);
    contem('inviável: diz o tempo real', aviso.textContent, 'cerca de 1h 14min');
    contem('inviável: diz que passa do configurado', aviso.textContent, 'passar do tempo configurado');
    contem('inviável: diz o tempo configurado', aviso.textContent, '5min não é suficiente para 50 mensagens');

    // --- não cabe E há menos pendentes -------------------------------------
    const [t1] = textoAvisoRitmo({
        session_target: 30, pendentes: 30, inviavel: true, tempo_total_estimado_fmt: '45min',
    }, 50, '5min');
    contem('inviável com menos pendentes: explica as duas coisas', t1, 'Só há 30 contatos pendentes');
    contem('inviável com menos pendentes: tempo das 30', t1, 'cerca de 45min');

    // --- menos pendentes, cabe: tempo é a janela configurada ---------------
    const [t2, tom2] = textoAvisoRitmo({
        session_target: 10, pendentes: 10, inviavel: false, tempo_total_estimado_fmt: '58min',
    }, 50, '1h');
    contem('menos pendentes e cabe: avisa', t2, 'serão enviadas 10 mensagens, não 50');
    contem('menos pendentes e cabe: tempo é o configurado', t2, 'Deve levar cerca de 1h');
    checar('menos pendentes e cabe: tom de atenção, não erro', tom2, 'atencao');

    // --- nenhum pendente ---------------------------------------------------
    const [t3] = textoAvisoRitmo({ session_target: 0, pendentes: 0, inviavel: false, tempo_total_estimado_fmt: '0s' }, 50, '5min');
    contem('nenhum pendente: diz que nada será enviado', t3, 'nada será enviado');

    // --- tudo certo: sem aviso ---------------------------------------------
    respostaEstimate = {
        status: 'ok', session_target: 50, pendentes: 80, inviavel: false,
        tempo_total_estimado_seg: 14400, tempo_total_estimado_fmt: '4h',
    };
    elementos['cfg-tempo'].value = '240';
    updateEstimativa();
    await rodarDebounce();
    checar('pedido cabe e há pendentes de sobra: sem aviso', visivel(), false);

    // --- sem planilha / sem servidor: a checagem local assume --------------
    elementos['cfg-tempo'].value = '5';
    respostaEstimate = { status: 'sem_planilha' };
    updateEstimativa();
    await rodarDebounce();
    checar('sem planilha: aviso local aparece', visivel(), true);
    contem('sem planilha: é o aviso do piso de 15s', aviso.textContent, 'Ritmo apertado');

    respostaEstimate = 'falha';
    updateEstimativa();
    await rodarDebounce();
    checar('servidor fora do ar: aviso local aparece', visivel(), true);

    // --- a estimativa lê a TELA, e o ↺ refaz a conta ----------------------
    // Relato: clicar no ↺ (voltar a Pendente) não mudava o aviso, porque o ↺
    // só grava no "Salvar Alterações" e a estimativa lia o disco.
    function linha(enviado) {
        const campos = {
            '.contact-pessoa': stubEl({ value: 'Ana' }),
            '.contact-numero': stubEl({ value: '(19) 99999-0001' }),
            '.contact-mensagem': stubEl({ value: 'Oi' }),
            '.contact-arquivo': stubEl({ value: '' }),
        };
        const tr = stubEl({ dataset: { enviado: enviado ? '1' : '0', invalido: '0' } });
        tr.querySelector = (sel) => campos[sel] || stubEl();
        return tr;
    }
    const tr = linha(true);
    linhasDaTabela = [tr];
    respostaEstimate = {
        status: 'ok', session_target: 1, pendentes: 1, inviavel: false,
        tempo_total_estimado_seg: 69, tempo_total_estimado_fmt: '1min 9s',
    };
    chamadas.length = 0;
    const btn = stubEl({ closest: () => tr });
    sandbox.resetContact(btn);
    await rodarDebounce();
    checar('↺ dispara uma nova estimativa', chamadas.length, 1);
    const [url, opts] = chamadas[0] || ['', {}];
    checar('com a tabela carregada, estima pela tela (POST)', [url, opts.method], ['/estimate', 'POST']);
    const corpo = JSON.parse(opts.body || '{}');
    checar('e manda o contato já como pendente', corpo.contacts && corpo.contacts[0].enviado, false);
    checar('junto com a configuração', [corpo.total_msgs, corpo.tempo_minutos], [50, 5]);

    // Tabela vazia (primeira vez, sem planilha): não há tela a descrever.
    linhasDaTabela = [];
    chamadas.length = 0;
    updateEstimativa();
    await rodarDebounce();
    checar('sem tabela, cai no disco (GET)', chamadas[0] && !chamadas[0][1].method, true);

    console.log(falhas === 0 ? '\nTudo passou.' : `\n${falhas} falha(s).`);
    process.exit(falhas === 0 ? 0 : 1);
})();
