// Log: bloco mesclado da pré-visualização do plano de rajadas (levas).
//
// O backend manda cada linha do plano ("📊 No total...", "🗓️ Como o envio
// vai acontecer:", cada "• leva N de M: ...") como uma chamada separada de
// self._log() — cada uma chega com seu próprio [HH:MM:SS]. Isso gerava uma
// "parede de horários" repetidos no log. addLogEntry() agora mescla essas
// linhas num único quadro amarelo (.log-plano), sem repetir o horário.
//
// Uso:  node tests/test_log_burst_plano.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const raiz = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(raiz, 'static', 'index.html'), 'utf8');
const src = html.split('<script>')[1].split('</script>')[0];
const css = html.split('<style>')[1].split('</style>')[0];

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

let logArea;
function novaLogArea() {
    logArea = {
        innerHTML: '', scrollTop: 0, scrollHeight: 0, children: [],
        querySelector: () => null,
        appendChild(el) { this.children.push(el); },
        removeChild(el) { this.children = this.children.filter(c => c !== el); },
        get firstChild() { return this.children[0]; },
    };
    return logArea;
}
novaLogArea();

const sandbox = {
    console: { log: () => {}, warn: () => {}, error: () => {} },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: {
        getElementById: (id) => (id === 'log-area' ? logArea : stubEl()),
        addEventListener() {},
        createElement: () => ({ className: '', title: '', textContent: '' }),
        querySelectorAll: () => [],
        activeElement: null,
    },
    window: {}, fetch: () => Promise.resolve({ ok: true, json: () => ({}) }),
    EventSource: function () { return { close() {}, addEventListener() {} }; },
    setTimeout, Number, String, Math, JSON, parseInt, RegExp,
};

vm.runInNewContext(src, sandbox);

const { addLogEntry, restoreLogsFromServer } = sandbox;
for (const [nome, fn] of Object.entries({ addLogEntry, restoreLogsFromServer })) {
    if (typeof fn !== 'function') throw new Error(`${nome} não encontrada em static/index.html`);
}

let falhas = 0;
function checar(titulo, ok, detalhe) {
    if (!ok) falhas++;
    console.log(`${ok ? 'PASSOU' : 'FALHOU'}  ${titulo}`);
    if (!ok && detalhe) console.log(`   ${detalhe}`);
}

// Linhas exatamente como WhatsAppSender._log_burst_plan_friendly as manda,
// já com o prefixo [HH:MM:SS] que add_log() adiciona no backend.
const linhas = [
    '[17:54:23] 📊 No total: 30 mensagens, distribuídas em 3 leva(s) ao longo de até 60 minutos.',
    '[17:54:23] 🗓️ Como o envio vai acontecer:',
    '[17:54:23]    • leva 1 de 3: envia 6 mensagens seguidas, depois espera 8 minutos antes de continuar',
    '[17:54:23]    • leva 2 de 3: envia 2 mensagens seguidas, depois espera 8 minutos antes de continuar',
    '[17:54:23]    • leva 3 de 3: envia 1 mensagem — é a última leva, o envio termina por aqui',
];

// --- As 5 linhas viram um único elemento no log ----------------------------
novaLogArea();
linhas.forEach(addLogEntry);
checar('as 5 linhas do plano viram um único bloco no DOM',
    logArea.children.length === 1, `children: ${logArea.children.length}`);

const bloco = logArea.children[0];
checar('o bloco usa a cor amarela dedicada (log-plano)',
    bloco.className.includes('log-plano'), `className: ${bloco.className}`);

checar('o horário [HH:MM:SS] não aparece em nenhuma linha do bloco mesclado',
    !/\[\d{2}:\d{2}:\d{2}\]/.test(bloco.textContent), `textContent: ${bloco.textContent}`);

checar('o bloco preserva as 5 linhas separadas por quebra de linha',
    bloco.textContent.split('\n').length === 5, `linhas: ${bloco.textContent.split('\n').length}`);

checar('a primeira e a última leva aparecem no texto mesclado',
    bloco.textContent.includes('leva 1 de 3') && bloco.textContent.includes('leva 3 de 3'),
    `textContent: ${bloco.textContent}`);

// --- Depois do bloco fechado, uma linha comum volta a criar um novo <div> --
addLogEntry('[17:54:24] ✅ Ana — mensagem enviada com sucesso.');
checar('linha comum após o bloco cria um novo elemento (bloco fechou sozinho)',
    logArea.children.length === 2, `children: ${logArea.children.length}`);
checar('a linha comum não herda a cor amarela do bloco',
    !logArea.children[1].className.includes('log-plano'), `className: ${logArea.children[1].className}`);

// --- restoreLogsFromServer (reconexão) também mescla corretamente ---------
novaLogArea();
restoreLogsFromServer(linhas);
checar('restoreLogsFromServer também mescla as 5 linhas num único bloco',
    logArea.children.length === 1, `children: ${logArea.children.length}`);

// --- .log-plano existe no CSS com white-space preservado -------------------
checar('.log-plano está definido no CSS com color e white-space: pre-wrap',
    /\.log-plano\s*\{[^}]*color:[^}]*white-space:\s*pre-wrap/.test(css), `css: ${css.match(/\.log-plano[^;]*;[^;]*;/)}`);

console.log(falhas === 0 ? '\nOK: todos os cenários passaram.' : `\nFALHA: ${falhas} cenário(s).`);
process.exit(falhas === 0 ? 0 : 1);
