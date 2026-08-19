// Painel: contagem regressiva precisa durante a pausa entre levas.
//
// Antes o painel só mostrava "Aguardando próxima rajada · N restantes", sem
// dizer quando a próxima leva ia começar. Agora o backend expõe pause_until
// (epoch de quando a leva retoma) e o frontend calcula uma contagem
// regressiva local (formatPauseDetail/startPauseCountdown), sem precisar de
// mais tráfego com o servidor a cada segundo.
//
// Também expõe next_leva_size (tamanho planejado da próxima leva): sem isso,
// "18 restantes" sozinho dava a entender que a próxima leva mandaria as 18
// de uma vez, quando na verdade é só uma fração (relato do usuário).
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

// --- nextLevaSize: deixa claro que só uma parte do "restante" sai agora ----
// Bug relatado: "18 restantes" sozinho dava a entender que a próxima leva
// mandaria as 18 de uma vez.
const textoComProxima = formatPauseDetail(daqui2min5s, 18, 6);
checar('com nextLevaSize, mostra quantas saem na próxima leva e o total restante',
    textoComProxima.includes('envia 6 de 18 restantes'), textoComProxima);
checar('sem nextLevaSize (ex: /status antigo), cai no texto anterior sem "envia"',
    !formatPauseDetail(daqui2min5s, 18).includes('envia'), formatPauseDetail(daqui2min5s, 18));
checar('nextLevaSize também aparece no texto genérico sem pause_until',
    formatPauseDetail(null, 18, 6) === 'Aguardando próxima leva · envia 6 de 18 restantes',
    formatPauseDetail(null, 18, 6));

// --- startPauseCountdown escreve no elemento imediatamente ------------------
startPauseCountdown(Date.now() / 1000 + 60, 4);
checar('startPauseCountdown atualiza o texto do #progress-detail na hora',
    progressDetail.textContent.includes('4 restantes'), progressDetail.textContent);
stopPauseCountdown();

startPauseCountdown(Date.now() / 1000 + 60, 18, 6);
checar('startPauseCountdown propaga nextLevaSize para o texto',
    progressDetail.textContent.includes('envia 6 de 18 restantes'), progressDetail.textContent);
stopPauseCountdown();

console.log(falhas === 0 ? '\nOK: todos os cenários passaram.' : `\nFALHA: ${falhas} cenário(s).`);
process.exit(falhas === 0 ? 0 : 1);
