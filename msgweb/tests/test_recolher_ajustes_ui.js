// As seções de ajuste recolhem quando o envio começa, para o log aparecer.
//
// Pedido de usabilidade: com Configuração e Mensagem Global abertas (o anexo
// global vive dentro desta última), o log fica empurrado para fora da tela — ele é o último bloco da
// coluna e é quem tem `flex-1`, ou seja, fica com a sobra de altura. Começado o
// envio, o log é a única coisa que o usuário ainda tem para acompanhar, e essas
// seções já estão travadas pelo próprio envio.
//
// O caso que este teste existe para fixar é o do NÃO recolher: um `/start`
// recusado (licença inválida, anexo global sumido do disco, planilha vazia)
// devolve o usuário exatamente para essas seções. Esconder o que ele precisa
// corrigir, no momento em que ele precisa corrigir, é pior que não ter a
// funcionalidade.
//
// Uso:  node tests/test_recolher_ajustes_ui.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const raiz = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(raiz, 'static', 'index.html'), 'utf8');
const src = html.split('<script>')[1].split('</script>')[0];

function stubEl(extra) {
    return Object.assign({
        value: '', innerHTML: '', textContent: '', title: '', placeholder: '',
        checked: false, disabled: false, open: true, style: {}, files: [],
        dataset: {}, className: '',
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

// O anexo global NÃO tem seção própria: ele é parte da Mensagem Global e vive
// dentro do <details> dela. Se algum dia voltar a ser independente, é aqui que
// se descobre — o teste abaixo confere que cada id existe mesmo no HTML.
const SECOES = ['config-details', 'global-msg-details'];

const ids = SECOES.concat([
    'cfg-total-msgs-input', 'cfg-tempo', 'cfg-hora-inicio', 'cfg-hora-fim',
    'cfg-skip-weekends', 'cfg-human-behavior', 'cfg-allow-duplicates',
    'btn-save-config', 'global-msg-toggle', 'global-message',
    'settings-locked-hint', 'global-msg-toggle-label',
    'global-msg-status', 'control-status', 'btn-start', 'btn-stop',
    'btn-verificar', 'contacts-section', 'contacts-tbody', 'contacts-status',
    'upload-status', 'file-input', 'btn-add-contact', 'btn-upload-sheet',
    'btn-download-contacts', 'unsaved-indicator', 'global-anexo-toggle',
    'global-anexo-toggle-label', 'global-anexo-nome', 'global-anexo-status',
    'btn-global-anexo-escolher', 'btn-global-anexo-remover',
    'estimativa-aviso', 'verificar-progresso',
]);
const elementos = {};
ids.forEach(id => { elementos[id] = stubEl(); });
elementos['cfg-total-msgs-input'].value = '50';
elementos['cfg-tempo'].value = '60';
elementos['cfg-hora-inicio'].value = '08:00';
elementos['cfg-hora-fim'].value = '18:00';

// O que o /start vai responder neste cenário.
let startOk = true;
let startDetail = '';

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
    fetch: (url) => {
        if (url === '/start') {
            return Promise.resolve({
                ok: startOk,
                json: () => ({ status: startOk ? 'ok' : 'erro', detail: startDetail }),
            });
        }
        return Promise.resolve({
            ok: true,
            json: () => ({ status: 'ok', config: {}, contacts: [], logs: [] }),
        });
    },
    EventSource: function () { return { close() {}, addEventListener() {} }; },
    setTimeout, clearTimeout, Promise, Number, String, Math, JSON, Error, Set,
};

vm.runInNewContext(src, sandbox);

const { startSending, recolherAjustesParaMostrarOLog } = sandbox;
for (const [nome, fn] of Object.entries({ startSending, recolherAjustesParaMostrarOLog })) {
    if (typeof fn !== 'function') throw new Error(`${nome} não encontrada em static/index.html`);
}

let falhas = 0;
function checar(titulo, obtido, esperado) {
    const ok = JSON.stringify(obtido) === JSON.stringify(esperado);
    if (!ok) falhas++;
    console.log(`${ok ? 'PASSOU' : 'FALHOU'}  ${titulo}`);
    if (!ok) console.log(`   obtido: ${JSON.stringify(obtido)}   esperado: ${JSON.stringify(esperado)}`);
}

function abrirTodas() {
    SECOES.forEach(id => { elementos[id].open = true; });
}
function abertas() {
    return SECOES.filter(id => elementos[id].open);
}

(async () => {
    // --- as seções existem na tela com os ids esperados --------------------
    // Sem isto o recolher vira um no-op silencioso quando alguém renomear uma
    // seção: a função varre ids e ignora o que não acha.
    SECOES.forEach(id => {
        checar(`a seção ${id} existe no HTML`, html.includes(`id="${id}"`), true);
    });

    // --- envio iniciado com sucesso ----------------------------------------
    abrirTodas();
    startOk = true;
    await startSending();
    checar('envio iniciado: as seções de ajuste recolhem', abertas(), []);

    // --- /start recusado ---------------------------------------------------
    // O caso que importa: o usuário precisa das seções para corrigir o motivo.
    abrirTodas();
    startOk = false;
    startDetail = 'O anexo global não está mais no disco (promo.jpg).';
    await startSending();
    checar('envio recusado: as seções continuam abertas', abertas(), SECOES);
    checar('o anexo global não tem seção própria',
        html.includes('id="global-anexo-details"'), false);
    checar('envio recusado: o motivo aparece na tela',
        elementos['control-status'].textContent, startDetail);

    // --- a função sozinha, sem depender do fluxo de envio ------------------
    abrirTodas();
    recolherAjustesParaMostrarOLog();
    checar('recolher: idempotente, chamar de novo não quebra', abertas(), []);
    recolherAjustesParaMostrarOLog();
    checar('recolher: segue recolhido', abertas(), []);

    console.log(falhas === 0 ? '\nTudo passou.' : `\n${falhas} falha(s).`);
    process.exit(falhas === 0 ? 0 : 1);
})();
