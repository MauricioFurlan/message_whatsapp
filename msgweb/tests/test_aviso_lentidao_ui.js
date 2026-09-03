// Popup de "conexão instável / WhatsApp Web lento" na tela.
//
// O backend manda o aviso dentro do `status` (campo `alerta_lentidao`), e não
// como evento SSE próprio, para ele sobreviver a um F5 ou a uma queda da
// conexão no meio do envio — ver tests/test_aviso_lentidao.py.
//
// O preço disso é que o mesmo aviso chega DE NOVO a cada heartbeat de status
// (a cada 5s). Sem o controle de `seq`, o popup reabriria sozinho toda vez,
// inclusive logo depois de o usuário fechá-lo — pior do que não avisar, porque
// deixa a tela inutilizável durante um envio de 2h que é exatamente quando o
// aviso aparece.
//
// Uso:  node tests/test_aviso_lentidao_ui.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const raiz = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(raiz, 'static', 'index.html'), 'utf8');
const src = html.split('<script>')[1].split('</script>')[0];

// O modal precisa existir no HTML, e nascer escondido.
if (!html.includes('id="lentidao-overlay"')) {
    throw new Error('modal #lentidao-overlay não existe em static/index.html');
}

function stubEl(extra) {
    return Object.assign({
        value: '', innerHTML: '', textContent: '', title: '', style: {}, hidden: false,
        checked: false, disabled: false, dataset: {}, className: '',
        classList: {
            _set: new Set(['hidden']),
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

const elementos = {};
['lentidao-overlay', 'lentidao-titulo', 'lentidao-msg', 'lentidao-dica-reenvio'].forEach(id => {
    elementos[id] = stubEl();
});

const sandbox = {
    console: { log: () => {}, warn: () => {}, error: () => {} },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: {
        getElementById: (id) => elementos[id] || stubEl(),
        addEventListener() {},
        // escapeHtml() do index.html escapa via um <div> de verdade
        // (textContent -> innerHTML). O stub precisa desse comportamento, senão
        // qualquer texto passado por ele some da mensagem sem o teste perceber.
        createElement: () => {
            let texto = '';
            return {
                get textContent() { return texto; },
                set textContent(v) { texto = String(v == null ? '' : v); },
                get innerHTML() {
                    return texto.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                },
            };
        },
        createTextNode: (t) => ({ nodeValue: t }),
        querySelectorAll: () => [], activeElement: null,
    },
    window: { innerWidth: 1280, innerHeight: 800 },
    fetch: () => Promise.resolve({ ok: true, json: () => ({ status: 'ok' }) }),
    EventSource: function () { return { close() {}, addEventListener() {} }; },
    setTimeout, clearTimeout, Promise, Number, String, Math, JSON, Error, Set,
};

vm.runInNewContext(src, sandbox);

const { mostrarAvisoLentidao, fecharAvisoLentidao } = sandbox;
for (const [nome, fn] of Object.entries({ mostrarAvisoLentidao, fecharAvisoLentidao })) {
    if (typeof fn !== 'function') throw new Error(`${nome} não encontrada em static/index.html`);
}

let falhas = 0;
function checar(titulo, obtido, esperado) {
    const ok = JSON.stringify(obtido) === JSON.stringify(esperado);
    if (!ok) falhas++;
    console.log(`${ok ? 'PASSOU' : 'FALHOU'}  ${titulo}`);
    if (!ok) console.log(`   obtido: ${JSON.stringify(obtido)}   esperado: ${JSON.stringify(esperado)}`);
}

const visivel = () => !elementos['lentidao-overlay'].classList.contains('hidden');

const alerta = {
    seq: 6, falhas: 6, tentativas: 12, percentual: 50,
    atraso_estimado_fmt: '20min', sem_conexao: false,
};

// --- envio saudável: nenhum popup ----------------------------------------
mostrarAvisoLentidao(null);
checar('status sem alerta não abre popup', visivel(), false);

// --- primeiro aviso -------------------------------------------------------
mostrarAvisoLentidao(alerta);
checar('alerta novo abre o popup', visivel(), true);
checar('título fala de lentidão, não de queda de conexão',
    elementos['lentidao-titulo'].textContent, 'Conexão instável ou WhatsApp Web lento');
checar('mensagem traz os números do backend',
    ['6 de 12', '(50%)', '20min'].filter(t => !elementos['lentidao-msg'].innerHTML.includes(t)), []);

// --- o usuário fecha, e o heartbeat repete o MESMO alerta ------------------
fecharAvisoLentidao();
checar('botão fecha o popup', visivel(), false);

mostrarAvisoLentidao(alerta);
mostrarAvisoLentidao(alerta);
checar('mesmo alerta (heartbeat de 5s) não reabre o popup', visivel(), false);

// --- a situação piorou: aviso novo, seq novo ------------------------------
const piorou = Object.assign({}, alerta, {
    seq: 11, falhas: 11, tentativas: 20, percentual: 55, atraso_estimado_fmt: '36min',
});
mostrarAvisoLentidao(piorou);
checar('seq novo reabre o popup', visivel(), true);
checar('mensagem atualiza para os números novos',
    ['11 de 20', '(55%)', '36min'].filter(t => !elementos['lentidao-msg'].innerHTML.includes(t)), []);

// --- falha do app: texto e dica diferentes --------------------------------
fecharAvisoLentidao();
mostrarAvisoLentidao({
    seq: 21, falhas: 3, falhas_app: 3, tentativas: 6, percentual: 50,
    atraso_estimado_fmt: '11min', sem_conexao: false, tipo: 'app',
});
checar('falha do app tem título próprio',
    elementos['lentidao-titulo'].textContent, 'O WhatsApp Web não está carregando');
checar('falha do app diz que os contatos seguem pendentes',
    elementos['lentidao-msg'].innerHTML.includes('continuam pendentes'), true);
checar('falha do app NÃO fala em inválido',
    elementos['lentidao-msg'].innerHTML.toLowerCase().includes('inválid'), false);
// Falha de app não marca contato nenhum: não há linha para reenviar com ↺.
checar('dica de reenvio some na falha do app',
    elementos['lentidao-dica-reenvio'].hidden, true);

fecharAvisoLentidao();
mostrarAvisoLentidao({
    seq: 26, falhas: 5, falhas_app: 0, tentativas: 10, percentual: 50,
    atraso_estimado_fmt: '16min', sem_conexao: false, tipo: 'chat',
});
checar('dica de reenvio volta na falha de conversa',
    elementos['lentidao-dica-reenvio'].hidden, false);

// --- sem internet: título diferente ---------------------------------------
fecharAvisoLentidao();
mostrarAvisoLentidao(Object.assign({}, piorou, { seq: 16, sem_conexao: true }));
checar('sem conexão tem título próprio',
    elementos['lentidao-titulo'].textContent, 'Sem conexão com a internet');

if (falhas) {
    console.log(`\n${falhas} teste(s) falharam.`);
    process.exit(1);
}
console.log('\nTodos os testes passaram.');
