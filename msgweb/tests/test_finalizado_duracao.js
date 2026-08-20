// Painel: duração real do envio mostrada ao concluir ("Finalizado").
//
// O usuário perguntou se era possível ver quanto tempo o envio realmente
// levou do primeiro ao último contato. O backend expõe elapsed_seconds em
// get_status() (apurado ao chegar em "finalizado" com sucesso), e o
// frontend formata isso em texto legível (formatDuration) e mostra no
// detalhe do painel.
//
// Uso:  node tests/test_finalizado_duracao.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const raiz = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(raiz, 'static', 'index.html'), 'utf8');
const src = html.split('<script>')[1].split('</script>')[0];

function stubEl() {
    return {
        value: '', innerHTML: '', textContent: '', title: '', placeholder: '',
        checked: false, disabled: false, style: {}, files: [], dataset: {},
        classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
        addEventListener() {}, querySelector: () => stubEl(),
        querySelectorAll: () => [], insertAdjacentHTML() {}, remove() {}, focus() {},
        closest: () => null, appendChild() {}, removeChild() {}, children: [],
    };
}

const elementos = {};
function elementoDe(id) {
    if (!elementos[id]) elementos[id] = stubEl();
    return elementos[id];
}

const sandbox = {
    console: { log: () => {}, warn: () => {}, error: () => {} },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: {
        getElementById: elementoDe,
        addEventListener() {},
        createElement: () => stubEl(),
        querySelectorAll: () => [],
        activeElement: null,
    },
    window: {}, fetch: () => Promise.resolve({ ok: true, json: () => ({}) }),
    EventSource: function () { return { close() {}, addEventListener() {} }; },
    setTimeout, clearTimeout, setInterval, clearInterval, Date, Number, String, Math, JSON,
};

vm.runInNewContext(src, sandbox);

const { formatDuration, updateProgressBar } = sandbox;
for (const [nome, fn] of Object.entries({ formatDuration, updateProgressBar })) {
    if (typeof fn !== 'function') throw new Error(`${nome} não encontrada em static/index.html`);
}

let falhas = 0;
function checar(titulo, ok, detalhe) {
    if (!ok) falhas++;
    console.log(`${ok ? 'PASSOU' : 'FALHOU'}  ${titulo}`);
    if (!ok && detalhe) console.log(`   ${detalhe}`);
}

// --- formatDuration ---------------------------------------------------------
checar('segundos', formatDuration(8) === '8s', formatDuration(8));
checar('minutos e segundos', formatDuration(65) === '1min 5s', formatDuration(65));
checar('minutos exatos, sem "0s" sobrando', formatDuration(120) === '2min', formatDuration(120));
checar('horas e minutos', formatDuration(3661) === '1h 1min', formatDuration(3661));
checar('nunca fica negativo', formatDuration(-5) === '0s', formatDuration(-5));

// --- Integração: updateProgressBar no estado "finalizado" ------------------
updateProgressBar({
    state: 'finalizado', messages_sent: 10, total_pending: 0, session_target: 10,
    elapsed_seconds: 125,
});
checar('mostra a duração no detalhe ao finalizar com elapsed_seconds',
    elementoDe('progress-detail').textContent.includes('concluído em 2min 05s') === false
    && elementoDe('progress-detail').textContent.includes('concluído em 2min 5s'),
    elementoDe('progress-detail').textContent);

updateProgressBar({
    state: 'finalizado', messages_sent: 3, total_pending: 0, session_target: 3,
    elapsed_seconds: null,
});
checar('sem elapsed_seconds (compat com /status antigo), não quebra e não inventa duração',
    elementoDe('progress-detail').textContent === 'Todas as mensagens foram enviadas',
    elementoDe('progress-detail').textContent);

console.log(falhas === 0 ? '\nOK: todos os cenários passaram.' : `\nFALHA: ${falhas} cenário(s).`);
process.exit(falhas === 0 ? 0 : 1);
