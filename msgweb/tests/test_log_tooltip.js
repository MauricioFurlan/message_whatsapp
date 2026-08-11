// Log: cor e tooltip por tipo de problema.
//
// Cada contato inválido/falha tem uma ação diferente por trás, então cada motivo
// tem sua própria cor no log e um tooltip explicando o que aconteceu e o que
// fazer. Este teste trava as duas coisas.
//
// Os textos testados aqui são exatamente os que o whatsapp_sender.py manda pelo
// log — se uma mensagem do sender mudar, este teste falha e avisa que a
// classificação ficou órfã.
//
// Uso:  node tests/test_log_tooltip.js
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

// Área de log de mentira: guarda as linhas criadas por addLogEntry
const logArea = {
    innerHTML: '', scrollTop: 0, scrollHeight: 0, children: [],
    querySelector: () => null,
    appendChild(el) { this.children.push(el); },
    removeChild(el) { this.children = this.children.filter(c => c !== el); },
    get firstChild() { return this.children[0]; },
};

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
    setTimeout, Number, String, Math, JSON,
};

vm.runInNewContext(src, sandbox);

const { logProblemInfo, logTooltip, addLogEntry } = sandbox;
for (const [nome, fn] of Object.entries({ logProblemInfo, logTooltip, addLogEntry })) {
    if (typeof fn !== 'function') throw new Error(`${nome} não encontrada em static/index.html`);
}

let falhas = 0;
function checar(titulo, ok, detalhe) {
    if (!ok) falhas++;
    console.log(`${ok ? 'PASSOU' : 'FALHOU'}  ${titulo}`);
    if (!ok && detalhe) console.log(`   ${detalhe}`);
}

// Espera cor própria + tooltip contendo todos os trechos informados.
function problema(titulo, mensagem, cor, trechos) {
    const info = logProblemInfo(mensagem);
    if (!info) {
        checar(titulo, false, `sem classificação para: ${mensagem}`);
        return;
    }
    const faltando = trechos.filter(t => !info.motivo.includes(t));
    const corOk = info.cor === cor;
    checar(`${titulo} [${cor}]`, corOk && faltando.length === 0,
        `cor: ${info.cor} (esperada ${cor})\n   faltou no tooltip: ${faltando.join(' | ') || '-'}`);
}

function semProblema(titulo, mensagem) {
    const info = logProblemInfo(mensagem);
    checar(titulo, info === null, `classificação inesperada: ${JSON.stringify(info)}`);
}

// --- Dado errado na planilha (laranja) -------------------------------------
problema('mensagem vazia explica a coluna Mensagem e a mensagem global',
    '❌ Ana (11999998888) — mensagem vazia, marcado como inválido (pulado sem abrir o WhatsApp).',
    'log-sheet', ['coluna Mensagem está vazia', 'mensagem global']);

problema('número ausente explica a coluna Número',
    '❌ Ana () — número ausente, marcado como inválido (pulado sem abrir o WhatsApp).',
    'log-sheet', ['coluna Número está vazia', 'DDD']);

problema('número curto explica a contagem de dígitos',
    '❌ Ana (999) — número inválido, marcado como inválido (pulado sem abrir o WhatsApp).',
    'log-sheet', ['menos de 10 dígitos', 'DDD']);

// --- Número recusado pelo WhatsApp (vermelho) ------------------------------
problema('timeout explica conta inexistente e também conexão instável',
    '❌ Ana (11999998888) — número inválido ou não encontrado no WhatsApp, marcado como inválido.',
    'log-nowhats', ['não tem conta no WhatsApp', 'internet lenta', 'reenviar']);

// --- Falhas de envio -------------------------------------------------------
problema('abandono mostra quantas falhas e o motivo',
    '❌ Ana — falhou 3x (erro no envio). Desistindo deste contato para não travar as próximas rodadas.',
    'log-giveup', ['3 vezes seguidas', 'erro no envio', 'limite de tentativas']);

problema('retentativa deixa claro que o contato ainda está pendente',
    '⚠️ Ana — falha ao enviar (erro no envio). Tentativa 1/3, será tentado novamente na próxima rodada.',
    'log-retry', ['tentativa 1 de 3', 'continua pendente', 'Ainda não é um contato inválido']);

problema('erro inesperado aponta o arquivo de log',
    '⚠️ Ana (11999998888) — erro inesperado: Message: element not interactable',
    'log-tech', ['arquivo de log', 'continua pendente']);

// --- Linhas puladas (cinza) -----------------------------------------------
problema('[SKIP] de inválido diz que a marcação veio de antes',
    '[SKIP] Ana — número inválido, pulando.',
    'log-skipped', ['já estava marcado como inválido', 'Invalido = X', 'reenviar']);

semProblema('[SKIP] de já enviado não é problema', '[SKIP] Ana — já enviado, pulando.');

// --- Linhas comuns --------------------------------------------------------
semProblema('linha de envio normal', 'Enviando para Ana (11999998888)...');
semProblema('linha de sucesso', '✅ Ana — mensagem enviada com sucesso.');
semProblema('linha de rodada', '📤 Rodada 1/3 iniciada');
semProblema('mensagem vazia (string vazia)', '');

// --- Cores são todas distintas e existem no CSS ---------------------------
const cores = ['log-sheet', 'log-nowhats', 'log-giveup', 'log-retry', 'log-tech', 'log-skipped'];
const definidas = cores.filter(c => new RegExp(`\\.${c}\\s*\\{[^}]*color:`).test(css));
checar('toda cor de problema tem regra no CSS do index.html',
    definidas.length === cores.length,
    `sem regra: ${cores.filter(c => !definidas.includes(c)).join(', ')}`);

const valores = cores.map(c => css.match(new RegExp(`\\.${c}\\s*\\{[^}]*color:\\s*([^;}]+)`))[1].trim());
checar('cores não se repetem entre tipos de problema',
    new Set(valores).size === cores.length, `valores: ${valores.join(', ')}`);

// --- Fiação: addLogEntry aplica cor + tooltip na linha --------------------
logArea.children = [];
addLogEntry('❌ Ana (999) — número inválido, marcado como inválido (pulado sem abrir o WhatsApp).');
addLogEntry('✅ Ana — mensagem enviada com sucesso.');
addLogEntry('[SKIP] Ana — número inválido, pulando.');

const [invalida, sucesso, skip] = logArea.children;
checar('linha inválida recebe a cor do motivo',
    invalida.className.includes('log-sheet'), `className: ${invalida.className}`);
checar('linha inválida recebe cursor de ajuda (log-help)',
    invalida.className.includes('log-help'), `className: ${invalida.className}`);
checar('linha inválida recebe o tooltip',
    invalida.title.includes('menos de 10 dígitos'), `title: ${invalida.title}`);
checar('linha de sucesso segue verde e sem tooltip',
    sucesso.className.includes('text-green-400') && sucesso.title === '',
    `className: ${sucesso.className} title: ${sucesso.title}`);
checar('linha [SKIP] inválida sai em cinza, não no amarelo genérico',
    skip.className.includes('log-skipped') && !skip.className.includes('text-yellow-400'),
    `className: ${skip.className}`);

console.log(falhas === 0 ? '\nOK: todos os cenários passaram.' : `\nFALHA: ${falhas} cenário(s).`);
process.exit(falhas === 0 ? 0 : 1);
