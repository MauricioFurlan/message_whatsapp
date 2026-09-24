// O anexo global na tela: parte da Mensagem Global, não uma seção à parte.
//
// A regra de negócio tem um gatilho só — a coluna Mensagem em branco — e o
// anexo viaja junto com o texto global. A tela precisa contar essa história
// certa, porque é nela que o usuário decide o que vai sair.
//
// Três coisas aqui que não são óbvias:
//
//   1. Desligar a mensagem global desliga o anexo. A garantia de verdade é do
//      backend (`_anexo_global_ativo` exige as duas), mas se a tela não fizesse
//      o mesmo, ela mostraria o anexo ligado enquanto o servidor já o ignorava.
//   2. O CAMINHO do arquivo sobrevive ao desligar — religar a mensagem global
//      não pode obrigar o usuário a escolher o arquivo de novo.
//   3. O pin da linha do contato diz o que aquele contato vai receber. Desde
//      que o anexo virou parte do pacote, dizer só "mensagem global" esconde
//      metade do que vai sair — inclusive o caso de só-anexo, em que não há
//      texto nenhum e mesmo assim o contato recebe algo.
//
// Uso:  node tests/test_anexo_global_ui.js
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

const ids = [
    'config-details', 'global-msg-details',
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
];
const elementos = {};
ids.forEach(id => { elementos[id] = stubEl(); });
elementos['cfg-total-msgs-input'].value = '50';
elementos['cfg-tempo'].value = '60';

// Duas linhas com a coluna Mensagem EM BRANCO — as duas entram no pacote
// global —, mas uma tem arquivo próprio e a outra não. É essa diferença que o
// pin tem que enxergar: o arquivo próprio afasta o anexo global daquela linha.
function linhaFalsa(mensagem, arquivo) {
    const campoMensagem = stubEl({ value: mensagem });
    const campoArquivo = stubEl({ value: arquivo });
    const tr = stubEl({
        querySelector: (sel) => {
            if (sel === '.contact-mensagem') return campoMensagem;
            if (sel === '.contact-arquivo') return campoArquivo;
            return stubEl();
        },
    });
    tr.campoMensagem = campoMensagem;
    tr.campoArquivo = campoArquivo;
    return tr;
}

const semArquivo = linhaFalsa('', '');
const comArquivo = linhaFalsa('', 'C:/media/contrato.pdf');
const campoMensagemDaLinha = semArquivo.campoMensagem;
const linhas = [semArquivo, comArquivo];

let posts = [];

const sandbox = {
    console: { log: () => {}, warn: () => {}, error: () => {} },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: {
        getElementById: (id) => elementos[id] || stubEl(),
        addEventListener() {},
        createElement: () => stubEl(),
        createTextNode: (t) => ({ nodeValue: t }),
        querySelectorAll: (sel) => (sel === '#contacts-tbody tr' ? linhas : []),
        activeElement: null,
    },
    window: { innerWidth: 1280, innerHeight: 800 },
    fetch: (url, opts) => {
        if (opts && opts.method === 'POST') posts.push({ url, body: opts.body });
        return Promise.resolve({
            ok: true,
            json: () => ({ status: 'ok', config: {}, contacts: [], logs: [] }),
        });
    },
    EventSource: function () { return { close() {}, addEventListener() {} }; },
    setTimeout, clearTimeout, Promise, Number, String, Math, JSON, Error, Set,
};

vm.runInNewContext(src, sandbox);

const {
    toggleGlobalMessage, toggleGlobalAnexo, updateGlobalMessageHints,
    mostrarAnexoGlobal, aplicarEstadoAnexoGlobal, saveGlobalMessage,
    onGlobalMessageInput, onGlobalMessageBlur,
} = sandbox;
for (const [nome, fn] of Object.entries({
    toggleGlobalMessage, toggleGlobalAnexo, updateGlobalMessageHints,
    mostrarAnexoGlobal, aplicarEstadoAnexoGlobal, saveGlobalMessage,
    onGlobalMessageInput, onGlobalMessageBlur })) {
    if (typeof fn !== 'function') throw new Error(`${nome} não encontrada em static/index.html`);
}

let falhas = 0;
function checar(titulo, obtido, esperado) {
    const ok = JSON.stringify(obtido) === JSON.stringify(esperado);
    if (!ok) falhas++;
    console.log(`${ok ? 'PASSOU' : 'FALHOU'}  ${titulo}`);
    if (!ok) console.log(`   obtido: ${JSON.stringify(obtido)}   esperado: ${JSON.stringify(esperado)}`);
}

(async () => {
    // --- o anexo mora dentro da Mensagem Global ----------------------------
    checar('não existe uma seção própria de Anexo Global',
        html.includes('id="global-anexo-details"'), false);
    checar('o controle do anexo existe dentro da tela',
        html.includes('id="global-anexo-toggle"'), true);

    // --- sem a mensagem global, o anexo nem é acessível --------------------
    elementos['global-msg-toggle'].checked = false;
    elementos['global-anexo-toggle'].checked = false;
    aplicarEstadoAnexoGlobal();
    checar('mensagem global desligada: o toggle do anexo fica desabilitado',
        elementos['global-anexo-toggle'].disabled, true);

    // --- ligando o pacote --------------------------------------------------
    elementos['global-msg-toggle'].checked = true;
    elementos['global-message'].value = 'Olá {nome}!';
    toggleGlobalMessage();
    checar('mensagem global ligada: o toggle do anexo libera',
        elementos['global-anexo-toggle'].disabled, false);

    mostrarAnexoGlobal('C:/media/promo.jpg', 'promo.jpg', true);
    elementos['global-anexo-toggle'].checked = true;
    toggleGlobalAnexo();
    checar('anexo ligado: o botão de escolher arquivo libera',
        elementos['btn-global-anexo-escolher'].disabled, false);
    checar('anexo ligado: o rótulo vira ON',
        elementos['global-anexo-toggle-label'].textContent, 'ON');

    // --- o pin conta a história certa --------------------------------------
    updateGlobalMessageHints();
    checar('pin: texto + anexo',
        campoMensagemDaLinha.placeholder, '📌 Mensagem global + anexo serão enviados');

    // O caso que este bloco existe para fixar: a linha COM arquivo próprio
    // recebe o texto global, mas o arquivo dela — não o anexo global. Prometer
    // "+ anexo" ali seria a tela contando uma coisa e o envio fazendo outra.
    checar('pin: linha com arquivo próprio não promete o anexo global',
        comArquivo.campoMensagem.placeholder, '📌 Mensagem global será usada');

    elementos['global-message'].value = '';
    updateGlobalMessageHints();
    checar('pin: só anexo, quando não há texto global',
        campoMensagemDaLinha.placeholder, '📌 Anexo global será enviado');

    // Sem texto global E com arquivo próprio, nada do pacote alcança esta
    // linha — ela recebe só o arquivo dela. Então não há pin nenhum.
    checar('pin: some quando a linha não recebe nada do pacote',
        comArquivo.campoMensagem.placeholder, '');

    elementos['global-message'].value = 'Olá {nome}!';
    elementos['global-anexo-toggle'].checked = false;
    updateGlobalMessageHints();
    checar('pin: só mensagem, quando não há anexo',
        campoMensagemDaLinha.placeholder, '📌 Mensagem global será usada');

    // Contato que escreveu a própria mensagem não entra no pacote: sem pin.
    campoMensagemDaLinha.value = 'escrevi a minha';
    updateGlobalMessageHints();
    checar('pin: some para quem escreveu a própria mensagem',
        campoMensagemDaLinha.placeholder, '');
    campoMensagemDaLinha.value = '';

    // --- o pin não pode ficar velho ----------------------------------------
    // Relatado em uso (23/09/2026): os dois ligados, texto ainda em branco (pin
    // dizendo "só o anexo"), o usuário escreve a mensagem e clica em Salvar — e
    // o pin continuava dizendo "só o anexo". A tela prometia menos do que o
    // envio ia fazer. `saveGlobalMessage` não reavaliava o pin, e o textarea da
    // mensagem global não tinha `oninput` (as linhas de contato tinham).
    elementos['global-message'].value = '';
    elementos['global-anexo-toggle'].checked = true;
    updateGlobalMessageHints();
    checar('ponto de partida do bug: pin diz só anexo',
        campoMensagemDaLinha.placeholder, '📌 Anexo global será enviado');

    elementos['global-message'].value = 'agora escrevi a mensagem';
    await saveGlobalMessage();
    checar('salvar a mensagem atualiza o pin',
        campoMensagemDaLinha.placeholder, '📌 Mensagem global + anexo serão enviados');

    // E digitando, sem salvar, o pin já acompanha.
    elementos['global-message'].value = '';
    onGlobalMessageInput();
    checar('apagar o texto volta o pin para só anexo',
        campoMensagemDaLinha.placeholder, '📌 Anexo global será enviado');

    elementos['global-message'].value = 'escrevendo de novo';
    onGlobalMessageInput();
    checar('digitar o texto atualiza o pin sem precisar salvar',
        campoMensagemDaLinha.placeholder, '📌 Mensagem global + anexo serão enviados');

    // --- o texto salva sozinho, como o anexo -------------------------------
    // O botão "Salvar Mensagem" saiu: dois controles vizinhos no mesmo bloco
    // com comportamentos diferentes (o anexo gravava sozinho, o texto exigia
    // clique) é o que fazia o usuário clicar e ficar na dúvida se funcionou.
    checar('o botão de salvar mensagem não existe mais',
        html.includes('id="btn-save-global-msg"'), false);

    elementos['global-message'].value = 'texto que acabou de ser digitado';
    posts = [];
    onGlobalMessageBlur();
    const postMsg = posts.filter(p => p.url === '/global-message').pop();
    checar('sair do campo grava a mensagem',
        postMsg ? JSON.parse(postMsg.body).mensagem : null,
        'texto que acabou de ser digitado');

    // Sair do campo sem ter mexido não pode gerar requisição: o blur dispara
    // toda vez que o usuário só passa pelo campo.
    posts = [];
    onGlobalMessageBlur();
    checar('sair do campo sem mudar nada não gera requisição',
        posts.filter(p => p.url === '/global-message'), []);

    // --- desligar a mensagem global desliga o anexo ------------------------
    elementos['global-anexo-toggle'].checked = true;
    elementos['global-msg-toggle'].checked = false;
    posts = [];
    toggleGlobalMessage();

    checar('desligou a mensagem global: o anexo desliga junto',
        elementos['global-anexo-toggle'].checked, false);
    checar('desligou a mensagem global: o pin some',
        campoMensagemDaLinha.placeholder, '');

    // O caminho do arquivo sobrevive: religar não pode pedir o arquivo de novo.
    checar('o nome do arquivo continua na tela',
        elementos['global-anexo-nome'].textContent, 'promo.jpg');
    const postAnexo = posts.filter(p => p.url === '/global-attachment').pop();
    if (postAnexo) {
        checar('o POST do anexo preserva o caminho e só zera o ativo',
            JSON.parse(postAnexo.body),
            { arquivo: 'C:/media/promo.jpg', ativo: false });
    }

    console.log(falhas === 0 ? '\nTudo passou.' : `\n${falhas} falha(s).`);
    process.exit(falhas === 0 ? 0 : 1);
})();
