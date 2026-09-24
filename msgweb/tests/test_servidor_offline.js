// Regressão: servidor desligado virava "sua licença não vale".
//
// Bug relatado pelo cliente: com o programa fechado, o usuário abria a página
// no navegador e ela carregava normalmente (o navegador servia o HTML do
// cache). Todas as chamadas falhavam e checkLicense() caía no catch, que
// abria o formulário "Ativação de Licença" — o usuário entendia que tinha
// perdido a licença. Ao ligar o programa, tudo voltava sozinho.
//
// Duas correções, uma de cada lado:
//   - app.py serve "/" com Cache-Control: no-store, então abrir a página sem
//     o servidor dá o erro de conexão do navegador, não a tela do app;
//   - checkLicense() separa "não falei com o servidor" de "licença inválida".
//
// Garantias verificadas aqui:
//   1. erro de rede NUNCA abre o overlay de licença — abre o de servidor offline
//   2. quando o servidor volta, a página se recarrega sozinha
//   3. HTTP 500 (servidor de pé, verificação quebrada) pede a chave, mas
//      dizendo que foi erro do servidor
//   4. licença válida não abre overlay nenhum
//
// Uso:  node tests/test_servidor_offline.js
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
        className: '',
        classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
        addEventListener() {}, querySelector: () => stubEl(),
        setAttribute() {}, getAttribute: () => null, removeAttribute() {},
        getBoundingClientRect: () => ({ top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }),
        querySelectorAll: () => [], insertAdjacentHTML() {}, remove() {}, focus() {},
        closest: () => null, appendChild() {}, removeChild() {}, children: [],
    };
}

// Overlay observável: guarda se está escondido, como o classList real faria.
function stubOverlay() {
    const el = stubEl();
    el.escondido = true;
    el.classList = {
        add: (c) => { if (c === 'hidden') el.escondido = true; },
        remove: (c) => { if (c === 'hidden') el.escondido = false; },
        toggle() {}, contains: (c) => c === 'hidden' && el.escondido,
    };
    return el;
}

const licenseOverlay = stubOverlay();
const offlineOverlay = stubOverlay();
const statusMsg = Object.assign(stubEl(), { textContent: '' });

const elementos = {
    'license-overlay': licenseOverlay,
    'offline-overlay': offlineOverlay,
    'license-status-msg': statusMsg,
};

let resposta = null;      // como /license/status deve responder
let urlsPedidas = [];
let reloads = 0;
let intervalosCriados = 0;

const sandbox = {
    console: { log: () => {}, warn: () => {}, error: () => {} },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: {
        getElementById: (id) => elementos[id] || stubEl(),
        addEventListener() {},
        createElement: () => stubEl(),
        createTextNode: (t) => ({ nodeValue: t }),
        querySelectorAll: () => [],
        activeElement: null,
    },
    window: { innerWidth: 1280, innerHeight: 800 },
    location: { reload: () => { reloads++; } },
    fetch: (url) => { urlsPedidas.push(url); return resposta(); },
    EventSource: function () { return { close() {}, addEventListener() {} }; },
    // O retry automático não deve rodar de verdade no teste: só contamos que
    // foi armado (e uma única vez, não um timer novo a cada tentativa).
    setInterval: () => { intervalosCriados++; return intervalosCriados; },
    clearInterval: () => {},
    setTimeout, clearTimeout, Promise, Number, String, Math, JSON, Error, Date,
};

vm.runInNewContext(src, sandbox);

const { checkLicense } = sandbox;
if (typeof checkLicense !== 'function') {
    throw new Error('checkLicense não encontrada em static/index.html');
}

let falhas = 0;
function checar(titulo, obtido, esperado) {
    const ok = JSON.stringify(obtido) === JSON.stringify(esperado);
    if (!ok) falhas++;
    console.log(`${ok ? 'PASSOU' : 'FALHOU'}  ${titulo}`);
    if (!ok) console.log(`   obtido: ${JSON.stringify(obtido)}   esperado: ${JSON.stringify(esperado)}`);
}

(async () => {
    // --- 1. servidor desligado (fetch rejeita) -----------------------------
    resposta = () => Promise.reject(new TypeError('Failed to fetch'));
    await checkLicense();
    checar('offline: NÃO pede a chave de licença', licenseOverlay.escondido, true);
    checar('offline: avisa que o programa não está rodando', offlineOverlay.escondido, false);
    checar('offline: arma a reconexão automática', intervalosCriados, 1);

    // --- 2. continua offline: não empilha timers ---------------------------
    await checkLicense();
    checar('offline de novo: não cria um segundo timer', intervalosCriados, 1);
    checar('offline de novo: segue sem pedir a chave', licenseOverlay.escondido, true);

    // --- 3. o servidor volta ------------------------------------------------
    // A página inteira falhou ao iniciar (contatos, SSE, histórico), então a
    // recuperação é um reload, não remontar cada chamada na mão.
    resposta = () => Promise.resolve({ ok: true, json: () => ({ valida: true, dias_restantes: 30 }) });
    await checkLicense();
    checar('servidor voltou: recarrega a página', reloads, 1);
    checar('servidor voltou: não pede a chave', licenseOverlay.escondido, true);

    // --- 4. HTTP 500: servidor de pé, verificação quebrada ------------------
    resposta = () => Promise.resolve({ ok: false, status: 500, json: () => ({}) });
    await checkLicense();
    checar('erro 500: pede a chave', licenseOverlay.escondido, false);
    checar('erro 500: não diz que o programa está fechado', offlineOverlay.escondido, true);
    checar('erro 500: explica que foi erro do servidor',
        statusMsg.textContent.indexOf('erro no servidor') !== -1, true);

    // --- 5. licença válida --------------------------------------------------
    licenseOverlay.escondido = false;
    offlineOverlay.escondido = false;
    resposta = () => Promise.resolve({ ok: true, json: () => ({ valida: true, dias_restantes: 12 }) });
    await checkLicense();
    checar('licença válida: nenhum overlay na frente', [licenseOverlay.escondido, offlineOverlay.escondido], [true, true]);

    // --- 6. licença realmente inválida --------------------------------------
    resposta = () => Promise.resolve({ ok: true, json: () => ({ valida: false, erro: 'expirada' }) });
    await checkLicense();
    checar('licença inválida: pede a chave', licenseOverlay.escondido, false);
    checar('licença inválida: não culpa a conexão', offlineOverlay.escondido, true);

    console.log(falhas === 0 ? '\nTodos os testes passaram.' : `\n${falhas} teste(s) falharam.`);
    process.exit(falhas === 0 ? 0 : 1);
})();
