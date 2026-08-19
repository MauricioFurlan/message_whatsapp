// Painel: contagem regressiva precisa durante a pausa entre levas.
//
// Antes o painel só mostrava "Aguardando próxima rajada · N restantes", sem
// dizer quando a próxima leva ia começar. Agora o backend expõe pause_until
// (epoch de quando a leva retoma) e o frontend calcula uma contagem
// regressiva local (formatPauseDetail/startPauseCountdown), sem precisar de
// mais tráfego com o servidor a cada segundo.
//
// Uso:  node tests/test_pause_countdown.js
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

const progressDetail = stubEl();
const sandbox = {
    console: { log: () => {}, warn: () => {}, error: () => {} },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: {
        getElementById: (id) => (id === 'progress-detail' ? progressDetail : stubEl()),
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

const { formatPauseDetail, startPauseCountdown, stopPauseCountdown } = sandbox;
for (const [nome, fn] of Object.entries({ formatPauseDetail, startPauseCountdown, stopPauseCountdown })) {
    if (typeof fn !== 'function') throw new Error(`${nome} não encontrada em static/index.html`);
}

let falhas = 0;
function checar(titulo, ok, detalhe) {
    if (!ok) falhas++;
    console.log(`${ok ? 'PASSOU' : 'FALHOU'}  ${titulo}`);
    if (!ok && detalhe) console.log(`   ${detalhe}`);
}

// --- Sem pause_until (compat com /status antigo) --------------------------
checar('sem pause_until, cai no texto genérico (plural)',
    formatPauseDetail(null, 5) === 'Aguardando próxima leva · 5 restantes',
    formatPauseDetail(null, 5));
checar('sem pause_until, singular quando falta 1',
    formatPauseDetail(null, 1) === 'Aguardando próxima leva · 1 restante',
    formatPauseDetail(null, 1));
checar('usa "leva", não "rajada"',
    !formatPauseDetail(null, 5).includes('rajada'), formatPauseDetail(null, 5));

// --- Com pause_until: contagem regressiva precisa --------------------------
const daqui2min5s = Date.now() / 1000 + 125;
const texto = formatPauseDetail(daqui2min5s, 3);
checar('mostra minutos e segundos restantes (~2min 05s)',
    /2min 0[4-6]s/.test(texto), texto);
checar('mostra o horário absoluto de retomada (às HH:MM)',
    /às \d{2}:\d{2}/.test(texto), texto);
checar('mantém a contagem de restantes',
    texto.includes('3 restantes'), texto);

const daqui40s = Date.now() / 1000 + 40;
checar('menos de 1 min mostra só segundos, sem "0min"',
    /^Próxima leva em 4[0-1]s/.test(formatPauseDetail(daqui40s, 2)),
    formatPauseDetail(daqui40s, 2));

const jaPassou = Date.now() / 1000 - 10;
checar('pause_until no passado não fica negativo (trava em 0s)',
    formatPauseDetail(jaPassou, 1).includes('0s'), formatPauseDetail(jaPassou, 1));

// --- startPauseCountdown escreve no elemento imediatamente ------------------
startPauseCountdown(Date.now() / 1000 + 60, 4);
checar('startPauseCountdown atualiza o texto do #progress-detail na hora',
    progressDetail.textContent.includes('4 restantes'), progressDetail.textContent);
stopPauseCountdown();

console.log(falhas === 0 ? '\nOK: todos os cenários passaram.' : `\nFALHA: ${falhas} cenário(s).`);
process.exit(falhas === 0 ? 0 : 1);
