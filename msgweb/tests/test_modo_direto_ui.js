// Modo "envio direto" na tela.
//
// Regras do usuário (2026-10-03/04): a opção desliga as rajadas; o aviso de
// risco de bloqueio aparece ao escolher o modo; "Quantas mensagens?" e "Em
// quanto tempo?" ficam desabilitados (valores guardados para a volta às
// rajadas) e a estimativa mostra "N pendentes, ~Xh Ymin". O backend é quem
// garante o comportamento (tests/e2e/test_e2e_direto.py); aqui se verifica a
// metade visível — e que a trava do envio não reabilita os campos que o modo
// mantém desligados, o mesmo cuidado que a mensagem global já tem.
//
// Uso:  node tests/test_modo_direto_ui.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const raiz = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(raiz, 'static', 'index.html'), 'utf8');
const src = html.split('<script>')[1].split('</script>')[0];

function stubEl(extra) {
    return Object.assign({
        value: '', innerHTML: '', textContent: '', title: '', placeholder: '',
        checked: false, disabled: false, style: {}, files: [], dataset: {},
        className: '',
        classList: {
            _set: new Set(),
            add(c) { this._set.add(c); },
            remove(c) { this._set.delete(c); },
            toggle(c, on) { if (on === undefined) { this._set.has(c) ? this._set.delete(c) : this._set.add(c); } else if (on) { this._set.add(c); } else { this._set.delete(c); } },
            contains(c) { return this._set.has(c); },
        },
        addEventListener() {}, querySelector: () => stubEl(),
        querySelectorAll: () => [], insertAdjacentHTML() {}, remove() {}, focus() {},
        setAttribute() {}, getAttribute: () => null, removeAttribute() {},
        getBoundingClientRect: () => ({ top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }),
        closest: () => null, appendChild() {}, removeChild() {}, children: [],
    }, extra || {});
}

const ids = [
    'cfg-total-msgs-input', 'cfg-tempo', 'cfg-hora-inicio', 'cfg-hora-fim',
    'cfg-skip-weekends', 'cfg-human-behavior', 'cfg-allow-duplicates',
    'cfg-modo-direto', 'cfg-aviso-direto', 'cfg-estimativa', 'cfg-aviso-ritmo',
    'cfg-total-msgs-header', 'btn-save-config', 'settings-locked-hint',
    'config-status', 'global-msg-toggle', 'global-message', 'cfg-direto-horario',
];
const elementos = {};
ids.forEach(id => { elementos[id] = stubEl(); });
elementos['cfg-total-msgs-input'].value = '50';
elementos['cfg-tempo'].value = '60';
elementos['cfg-hora-inicio'].value = '08:00';
elementos['cfg-hora-fim'].value = '18:00';
elementos['cfg-aviso-direto'].classList.add('hidden');
elementos['cfg-direto-horario'].classList.add('hidden');
elementos['cfg-skip-weekends'].checked = true;

let requisicoes = [];   // { url, body }
let localStorageSalvo = {};

const sandbox = {
    console: { log: () => {}, warn: () => {}, error: () => {} },
    localStorage: {
        getItem: (k) => (k in localStorageSalvo ? localStorageSalvo[k] : null),
        setItem(k, v) { localStorageSalvo[k] = v; },
        removeItem(k) { delete localStorageSalvo[k]; },
    },
    document: {
        getElementById: (id) => elementos[id] || stubEl(),
        addEventListener() {},
        createElement: () => stubEl(),
        createTextNode: (t) => ({ nodeValue: t }),
        querySelectorAll: () => [],
        activeElement: null,
    },
    window: { innerWidth: 1280, innerHeight: 800 },
    fetch: (url, opts) => {
        requisicoes.push({ url, body: opts && opts.body ? JSON.parse(opts.body) : null });
        const json = url.startsWith('/estimate')
            ? { status: 'ok', modo_envio: 'direto', pendentes: 100, session_target: 100, tempo_total_estimado_fmt: '1h 45min' }
            : { status: 'ok', config: {} };
        return Promise.resolve({ ok: true, json: () => json });
    },
    EventSource: function () { return { close() {}, addEventListener() {} }; },
    setTimeout, clearTimeout, Promise, Number, String, Math, JSON, Error, Set,
};

vm.runInNewContext(src, sandbox);

const { aplicarModoEnvio, lockSettingsEditing, saveConfig, updateEstimativa, loadConfigFromLocalStorage } = sandbox;
for (const [nome, fn] of Object.entries({ aplicarModoEnvio, lockSettingsEditing, saveConfig, updateEstimativa, loadConfigFromLocalStorage })) {
    if (typeof fn !== 'function') throw new Error(`${nome} não encontrada em static/index.html`);
}

let falhas = 0;
function checar(titulo, obtido, esperado) {
    const ok = JSON.stringify(obtido) === JSON.stringify(esperado);
    if (!ok) falhas++;
    console.log(`${ok ? 'PASSOU' : 'FALHOU'}  ${titulo}`);
    if (!ok) console.log(`   obtido: ${JSON.stringify(obtido)}   esperado: ${JSON.stringify(esperado)}`);
}

const esperar = (ms) => new Promise(r => setTimeout(r, ms));
const quantidadeETempo = ['cfg-total-msgs-input', 'cfg-tempo'];
const desabilitados = (lista) => lista.filter(id => elementos[id].disabled);

(async () => {
    // --- a opção existe na tela, com o aviso de risco ----------------------
    checar('a opção "Envio direto" existe na tela',
        html.includes('id="cfg-modo-direto"'), true);
    const aviso = html.split('id="cfg-aviso-direto"')[1].split('</p>')[0];
    // O cliente é leigo (pedido do usuário, 2026-10-04): o aviso diz o que
    // acontece e o risco em palavras simples, sem termos do programa.
    // "Pendente" é a palavra que o cliente vê na coluna de status da
    // tabela, então diz exatamente quem vai receber.
    checar('o aviso diz quem recebe ("Pendente", como na tabela) e o risco',
        ['todo mundo da lista', 'Pendente', 'BLOQUEAR o seu número'].filter(t => !aviso.includes(t)), []);
    checar('o aviso não usa termos que o cliente não conhece',
        ['rajada', 'pausa', 'intervalo'].filter(t => aviso.toLowerCase().includes(t)), []);

    // --- ligar o modo ------------------------------------------------------
    elementos['cfg-modo-direto'].checked = true;
    aplicarModoEnvio();
    checar('ligado: quantidade e tempo desabilitados',
        desabilitados(quantidadeETempo), quantidadeETempo);
    checar('ligado: valores guardados para a volta às rajadas',
        [elementos['cfg-total-msgs-input'].value, elementos['cfg-tempo'].value], ['50', '60']);
    checar('ligado: aviso de risco visível',
        elementos['cfg-aviso-direto'].classList.contains('hidden'), false);

    // O horário comercial continua valendo, e a tela diz isso com os
    // horários que o cliente preencheu (pedido do usuário, 2026-10-04).
    checar('ligado: frase do horário visível',
        elementos['cfg-direto-horario'].classList.contains('hidden'), false);
    checar('ligado: frase do horário usa os valores da tela',
        elementos['cfg-direto-horario'].textContent,
        '🕗 Ele só manda das 08:00 às 18:00, e não manda no sábado nem no domingo. Fora desse horário, ele espera e continua depois sozinho.');
    elementos['cfg-hora-inicio'].value = '09:30';
    elementos['cfg-skip-weekends'].checked = false;
    aplicarModoEnvio();
    checar('ligado: frase acompanha a mudança de horário e do fim de semana',
        elementos['cfg-direto-horario'].textContent,
        '🕗 Ele só manda das 09:30 às 18:00. Fora desse horário, ele espera e continua depois sozinho.');
    elementos['cfg-hora-inicio'].value = '08:00';
    elementos['cfg-skip-weekends'].checked = true;
    aplicarModoEnvio();

    requisicoes = [];
    updateEstimativa();
    checar('ligado: estimativa imediata sem número inventado',
        elementos['cfg-estimativa'].textContent, 'Vai mandar para todo mundo que está como Pendente');
    await esperar(500);
    checar('ligado: a estimativa pede o modo direto ao servidor',
        requisicoes.map(r => r.url), ['/estimate?modo_envio=direto']);
    checar('ligado: estimativa mostra pendentes e tempo',
        elementos['cfg-estimativa'].textContent, '100 pessoa(s) como Pendente. Deve levar mais ou menos 1h 45min.');
    checar('ligado: sem aviso de "ritmo apertado" (não há prazo)',
        elementos['cfg-aviso-ritmo'].classList.contains('hidden'), true);

    requisicoes = [];
    await saveConfig();
    checar('ligado: config grava modo_envio=direto',
        requisicoes[0].body.modo_envio, 'direto');
    checar('ligado: e mantém quantidade/tempo para a volta',
        [requisicoes[0].body.total_msgs, requisicoes[0].body.tempo_minutos], [50, 60]);

    // --- trava do envio ----------------------------------------------------
    lockSettingsEditing(true);
    checar('travado: a própria opção fica desabilitada',
        elementos['cfg-modo-direto'].disabled, true);
    lockSettingsEditing(false);
    checar('destravado com modo direto: quantidade e tempo seguem desabilitados',
        desabilitados(quantidadeETempo), quantidadeETempo);
    checar('destravado: a opção volta a funcionar',
        elementos['cfg-modo-direto'].disabled, false);

    // --- desligar ----------------------------------------------------------
    elementos['cfg-modo-direto'].checked = false;
    aplicarModoEnvio();
    checar('desligado: quantidade e tempo voltam',
        desabilitados(quantidadeETempo), []);
    checar('desligado: aviso some',
        elementos['cfg-aviso-direto'].classList.contains('hidden'), true);
    checar('desligado: frase do horário some',
        elementos['cfg-direto-horario'].classList.contains('hidden'), true);
    requisicoes = [];
    await saveConfig();
    checar('desligado: config grava modo_envio=rajadas',
        requisicoes[0].body.modo_envio, 'rajadas');

    // --- restauração do localStorage --------------------------------------
    localStorageSalvo['whatsapp_config'] = JSON.stringify({
        total_msgs: 50, tempo_minutos: 60, modo_envio: 'direto',
    });
    loadConfigFromLocalStorage();
    checar('restaurado: opção ligada e campos desabilitados',
        [elementos['cfg-modo-direto'].checked, desabilitados(quantidadeETempo)],
        [true, quantidadeETempo]);

    console.log(falhas === 0 ? '\nTodos os testes passaram.' : `\n${falhas} teste(s) falharam.`);
    process.exit(falhas === 0 ? 0 : 1);
})();
