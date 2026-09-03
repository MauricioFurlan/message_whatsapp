// Regressão: GET /contacts falhando em silêncio.
//
// Bug relatado pelo cliente: ao abrir o app, a tabela de contatos aparecia
// vazia mesmo com a planilha restaurada (o aviso "planilha da sessão anterior"
// estava na tela). loadContacts() fazia `if (!response.ok) return;` e o catch
// só chamava console.warn — a tela ficava vazia para sempre, sem retry e sem
// nenhum aviso.
//
// O risco não é só cosmético: a tabela da tela é a fonte do POST /contacts,
// que REESCREVE a planilha inteira. Salvar com a tela vazia/incompleta apaga
// as marcas de "Enviado" e devolve à fila quem já recebeu a mensagem.
//
// Garantias verificadas aqui:
//   1. resposta vazia NUNCA substitui uma tabela já preenchida
//   2. falha de rede/HTTP tenta de novo e, persistindo, avisa e trava o salvar
//   3. saveContacts() bloqueado não emite POST (nem pelo botão, nem por Ctrl+S)
//   4. um carregamento bem-sucedido destrava tudo
//
// Uso:  node tests/test_load_contacts_falha.js
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

// Elementos com identidade própria: precisamos inspecionar o que aconteceu com eles.
const btnSalvar = Object.assign(stubEl(), { disabled: false, title: 'Ctrl+S' });
const uploadStatus = Object.assign(stubEl(), { textContent: '', className: '' });
const contactsStatus = Object.assign(stubEl(), { textContent: '', className: '' });
const tbody = Object.assign(stubEl(), { innerHTML: '' });

let linhas = [];          // linhas atualmente na tabela
let respostaGet = null;   // como o fetch GET /contacts deve responder
let postsFeitos = [];     // corpos enviados via POST /contacts

const elementos = {
    'btn-save-contacts': btnSalvar,
    'upload-status': uploadStatus,
    'contacts-status': contactsStatus,
    'contacts-tbody': tbody,
};

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
        if (opts && opts.method === 'POST') {
            postsFeitos.push(JSON.parse(opts.body));
            return Promise.resolve({ ok: true, json: () => ({ total: 0, pendentes: 0 }) });
        }
        return respostaGet();
    },
    EventSource: function () { return { close() {}, addEventListener() {} }; },
    setTimeout, clearTimeout, Promise, Number, String, Math, JSON, Error,
};

vm.runInNewContext(src, sandbox);

const { loadContacts, saveContacts } = sandbox;
for (const [nome, fn] of Object.entries({ loadContacts, saveContacts })) {
    if (typeof fn !== 'function') throw new Error(`${nome} não encontrada em static/index.html`);
}

let falhas = 0;
function checar(titulo, obtido, esperado) {
    const ok = JSON.stringify(obtido) === JSON.stringify(esperado);
    if (!ok) falhas++;
    console.log(`${ok ? 'PASSOU' : 'FALHOU'}  ${titulo}`);
    if (!ok) console.log(`   obtido: ${JSON.stringify(obtido)}   esperado: ${JSON.stringify(esperado)}`);
}

const contatoFake = { pessoa: 'Fulano', numero: '19999999999', mensagem: 'oi', arquivo: '', enviado: true, invalido: false, data_envio: '2026-08-26 10:00:00', motivo: '' };

(async () => {
    // --- 1. GET falha com HTTP 500 -----------------------------------------
    linhas = [];
    respostaGet = () => Promise.resolve({ ok: false, status: 500, json: () => ({}) });
    let ok = await loadContacts();
    checar('GET 500: loadContacts devolve false', ok, false);
    checar('GET 500: salvar fica desabilitado', btnSalvar.disabled, true);
    checar('GET 500: erro aparece na tela (vermelho)', uploadStatus.className.indexOf('text-red-600') !== -1, true);

    // --- 2. salvar bloqueado não emite POST (caminho do Ctrl+S) ------------
    postsFeitos = [];
    linhas = [{
        querySelector: (sel) => ({ value: sel === '.contact-numero' ? '19999999999' : 'Fulano' }),
        dataset: {},
    }];
    await saveContacts();
    checar('salvar bloqueado NÃO faz POST /contacts', postsFeitos.length, 0);
    checar('salvar bloqueado avisa o usuário', contactsStatus.className.indexOf('text-red-600') !== -1, true);

    // --- 3. resposta vazia não apaga tabela preenchida ---------------------
    // Cenário do bug: a planilha volta vazia (leitura falhou) e a tela já tem
    // contatos com "Enviado" marcado. Substituir seria perder esse estado.
    linhas = [{ querySelector: () => ({ value: 'x' }), dataset: {} }];
    tbody.innerHTML = '<tr>linha existente</tr>';
    respostaGet = () => Promise.resolve({ ok: true, json: () => ({ contacts: [] }) });
    ok = await loadContacts();
    checar('planilha vazia: loadContacts devolve false', ok, false);
    checar('planilha vazia: tabela da tela é preservada', tbody.innerHTML, '<tr>linha existente</tr>');
    checar('planilha vazia: salvar fica bloqueado', btnSalvar.disabled, true);

    // --- 4. tentativas: falha nas duas primeiras, sucesso na terceira ------
    let chamadas = 0;
    linhas = [];
    respostaGet = () => {
        chamadas++;
        if (chamadas < 3) return Promise.reject(new Error('rede caiu'));
        return Promise.resolve({ ok: true, json: () => ({ contacts: [contatoFake] }) });
    };
    ok = await loadContacts();
    checar('rede instável: repete e carrega na 3ª tentativa', ok, true);
    checar('rede instável: fez exatamente 3 chamadas', chamadas, 3);
    checar('carregou: salvar volta a funcionar', btnSalvar.disabled, false);

    // --- 5. depois de carregar, salvar volta a emitir POST -----------------
    postsFeitos = [];
    linhas = [{
        querySelector: (sel) => ({ value: sel === '.contact-numero' ? '19999999999' : 'Fulano' }),
        dataset: {},
    }];
    await saveContacts(true);
    checar('depois de carregar, salvar faz POST normalmente', postsFeitos.length, 1);

    // --- 6. tabela vazia de verdade pode ser renderizada vazia -------------
    // Planilha legítima sem contatos não deve disparar o alarme.
    linhas = [];
    tbody.innerHTML = 'sujeira';
    respostaGet = () => Promise.resolve({ ok: true, json: () => ({ contacts: [] }) });
    ok = await loadContacts();
    checar('planilha legitimamente vazia carrega sem bloquear', ok, true);
    checar('planilha legitimamente vazia: salvar liberado', btnSalvar.disabled, false);

    console.log(falhas === 0 ? '\nTodos os testes passaram.' : `\n${falhas} teste(s) falharam.`);
    process.exit(falhas === 0 ? 0 : 1);
})();
