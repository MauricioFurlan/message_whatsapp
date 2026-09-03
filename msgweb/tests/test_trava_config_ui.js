// Trava de configuração e mensagem global na tela, durante o envio.
//
// A garantia de verdade é do backend (tests/test_trava_durante_envio.py); aqui
// se verifica a metade visível: campos desabilitados, nenhum POST disparado com
// o envio em curso, e — o caso menos óbvio — `toggleGlobalMessage()` não
// repostando a mensagem. Essa função roda na CARGA DA PÁGINA restaurando o
// toggle do localStorage, então recarregar a tela no meio de um envio chegava a
// reescrever a mensagem global sozinha, trocando o texto dos contatos restantes.
//
// Uso:  node tests/test_trava_config_ui.js
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

// Todos os elementos que a trava toca, com identidade própria.
const ids = [
    'cfg-total-msgs-input', 'cfg-tempo', 'cfg-hora-inicio', 'cfg-hora-fim',
    'cfg-skip-weekends', 'cfg-human-behavior', 'cfg-allow-duplicates',
    'btn-save-config', 'global-msg-toggle', 'global-message',
    'btn-save-global-msg', 'settings-locked-hint', 'global-msg-toggle-label',
    'global-msg-status', 'control-status', 'btn-start', 'btn-stop',
    'contacts-section', 'contacts-tbody', 'contacts-status', 'upload-status',
    'file-input', 'btn-add-contact', 'btn-upload-sheet', 'btn-download-contacts',
];
const elementos = {};
ids.forEach(id => { elementos[id] = stubEl(); });
elementos['cfg-total-msgs-input'].value = '50';
elementos['cfg-tempo'].value = '60';
elementos['cfg-hora-inicio'].value = '08:00';
elementos['cfg-hora-fim'].value = '18:00';
elementos['global-message'].value = 'mensagem original';

let posts = [];   // toda requisição de escrita que sair daqui

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
    fetch: (url, opts) => {
        if (opts && opts.method === 'POST') posts.push(url);
        return Promise.resolve({ ok: true, json: () => ({ status: 'ok', config: {} }) });
    },
    EventSource: function () { return { close() {}, addEventListener() {} }; },
    setTimeout, clearTimeout, Promise, Number, String, Math, JSON, Error, Set,
};

vm.runInNewContext(src, sandbox);

const { lockSettingsEditing, saveConfig, saveGlobalMessage, toggleGlobalMessage } = sandbox;
for (const [nome, fn] of Object.entries({ lockSettingsEditing, saveConfig, saveGlobalMessage, toggleGlobalMessage })) {
    if (typeof fn !== 'function') throw new Error(`${nome} não encontrada em static/index.html`);
}

let falhas = 0;
function checar(titulo, obtido, esperado) {
    const ok = JSON.stringify(obtido) === JSON.stringify(esperado);
    if (!ok) falhas++;
    console.log(`${ok ? 'PASSOU' : 'FALHOU'}  ${titulo}`);
    if (!ok) console.log(`   obtido: ${JSON.stringify(obtido)}   esperado: ${JSON.stringify(esperado)}`);
}

const camposDeConfig = [
    'cfg-total-msgs-input', 'cfg-tempo', 'cfg-hora-inicio', 'cfg-hora-fim',
    'cfg-skip-weekends', 'cfg-human-behavior', 'cfg-allow-duplicates',
    'btn-save-config', 'global-msg-toggle',
];

(async () => {
    // --- envio em andamento ------------------------------------------------
    elementos['global-msg-toggle'].checked = true;   // mensagem global ligada
    lockSettingsEditing(true);

    checar('travado: todos os campos de config ficam desabilitados',
        camposDeConfig.filter(id => !elementos[id].disabled), []);
    checar('travado: textarea da mensagem global desabilitado',
        elementos['global-message'].disabled, true);
    checar('travado: botão de salvar mensagem global desabilitado',
        elementos['btn-save-global-msg'].disabled, true);
    checar('travado: aviso visível na tela',
        elementos['settings-locked-hint'].classList.contains('hidden'), false);

    posts = [];
    await saveConfig();
    checar('travado: saveConfig NÃO faz POST', posts, []);

    posts = [];
    await saveGlobalMessage();
    checar('travado: saveGlobalMessage NÃO faz POST', posts, []);

    // O caso do recarregamento de página: toggleGlobalMessage roda sozinho ao
    // restaurar o estado salvo e, sem guarda, reposta a mensagem global.
    posts = [];
    toggleGlobalMessage();
    checar('travado: toggleGlobalMessage NÃO reposta a mensagem', posts, []);

    // --- envio terminou ----------------------------------------------------
    lockSettingsEditing(false);

    checar('destravado: campos de config voltam a funcionar',
        camposDeConfig.filter(id => elementos[id].disabled), []);
    checar('destravado: aviso some',
        elementos['settings-locked-hint'].classList.contains('hidden'), true);
    checar('destravado: mensagem global liberada (toggle ligado)',
        elementos['global-message'].disabled, false);

    posts = [];
    await saveConfig();
    checar('destravado: saveConfig volta a fazer POST', posts, ['/config']);

    posts = [];
    await saveGlobalMessage();
    checar('destravado: saveGlobalMessage volta a fazer POST', posts, ['/global-message']);

    // --- destravar não pode reabilitar o que o toggle mantém desligado -----
    elementos['global-msg-toggle'].checked = false;
    lockSettingsEditing(false);
    checar('toggle OFF: textarea segue desabilitado mesmo destravado',
        elementos['global-message'].disabled, true);
    checar('toggle OFF: botão de salvar segue desabilitado',
        elementos['btn-save-global-msg'].disabled, true);

    // --- startSending ainda grava config e mensagem ANTES do /start --------
    // Este é o caminho que a trava poderia quebrar sem aparecer: startSending
    // marca `starting = true`, e o heartbeat do /status pode travar a tela
    // ANTES dos saves pré-envio rodarem. Se a trava valesse para eles, o envio
    // começaria com a configuração antiga — exatamente o bug de "comportamento
    // humano ficou no padrão OFF sem o usuário saber".
    elementos['global-msg-toggle'].checked = true;
    lockSettingsEditing(true);          // simula a tela já travada pelo `starting`
    posts = [];
    await sandbox.startSending();

    checar('startSending: grava config, mensagem global e dispara /start',
        posts, ['/config', '/global-message', '/start']);

    console.log(falhas === 0 ? '\nTodos os testes passaram.' : `\n${falhas} teste(s) falharam.`);
    process.exit(falhas === 0 ? 0 : 1);
})();
