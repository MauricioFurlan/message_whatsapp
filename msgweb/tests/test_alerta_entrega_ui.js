// Popup do alarme de entrega: as mensagens saem e não chegam.
//
// Mesmo mecanismo do aviso de lentidão (vive dentro do `status` para
// sobreviver a um F5 ou a uma queda de SSE num envio de horas; o `seq` impede
// o popup de reabrir a cada heartbeat de 5s) — ver tests/test_aviso_lentidao_ui.js.
//
// O que este teste protege é a DIFERENÇA entre os dois avisos, que é fácil de
// perder numa refatoração que os "unifique":
//
//   - lentidão -> "o envio continua normalmente, não precisa parar"
//   - entrega  -> "pare agora; continuar pode bloquear a conta"
//
// Mensagem não entregue em bloco é a assinatura do número sendo limitado pelo
// WhatsApp. Se este popup sair com o tom do outro, o cliente segue enviando e
// perde a conta — que é exatamente o desfecho que a feature existe para evitar.
//
// Uso:  node tests/test_alerta_entrega_ui.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const raiz = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(raiz, 'static', 'index.html'), 'utf8');
const src = html.split('<script>')[1].split('</script>')[0];

if (!html.includes('id="entrega-overlay"')) {
    throw new Error('modal #entrega-overlay não existe em static/index.html');
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
['entrega-overlay', 'entrega-msg', 'control-status', 'btn-stop'].forEach(id => {
    elementos[id] = stubEl();
});

// Registra as chamadas ao backend: o botão "Parar o envio" tem de realmente
// chamar POST /stop, não só fechar o popup.
const chamadas = [];

const sandbox = {
    console: { log: () => {}, warn: () => {}, error: () => {} },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: {
        getElementById: (id) => elementos[id] || stubEl(),
        addEventListener() {},
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
    fetch: (url, opts) => {
        chamadas.push({ url, method: (opts && opts.method) || 'GET' });
        return Promise.resolve({ ok: true, json: () => ({ status: 'ok' }) });
    },
    EventSource: function () { return { close() {}, addEventListener() {} }; },
    setTimeout, clearTimeout, Promise, Number, String, Math, JSON, Error, Set,
};

vm.runInNewContext(src, sandbox);

const { mostrarAvisoEntrega, fecharAvisoEntrega, pararPorAlertaDeEntrega } = sandbox;
for (const [nome, fn] of Object.entries({ mostrarAvisoEntrega, fecharAvisoEntrega, pararPorAlertaDeEntrega })) {
    if (typeof fn !== 'function') throw new Error(`${nome} não encontrada em static/index.html`);
}

let falhas = 0;
function checar(titulo, obtido, esperado) {
    const ok = JSON.stringify(obtido) === JSON.stringify(esperado);
    if (!ok) falhas++;
    console.log(`${ok ? 'PASSOU' : 'FALHOU'}  ${titulo}`);
    if (!ok) console.log(`   obtido: ${JSON.stringify(obtido)}   esperado: ${JSON.stringify(esperado)}`);
}

const visivel = () => !elementos['entrega-overlay'].classList.contains('hidden');

const alerta = { seq: 8, nao_entregues: 8, falharam: 0, verificadas: 10, percentual: 80 };

// --- envio saudável -------------------------------------------------------
mostrarAvisoEntrega(null);
checar('status sem alarme não abre popup', visivel(), false);

// --- primeiro alarme ------------------------------------------------------
mostrarAvisoEntrega(alerta);
checar('alarme novo abre o popup', visivel(), true);
checar('mensagem traz os números do backend',
    ['8 de 10', '(80%)'].filter(t => !elementos['entrega-msg'].innerHTML.includes(t)), []);

// --- o usuário fecha, e o heartbeat repete o MESMO alarme ------------------
fecharAvisoEntrega();
checar('botão fecha o popup', visivel(), false);

mostrarAvisoEntrega(alerta);
mostrarAvisoEntrega(alerta);
checar('mesmo alarme (heartbeat de 5s) não reabre o popup', visivel(), false);

// --- piorou: seq novo -----------------------------------------------------
mostrarAvisoEntrega({ seq: 14, nao_entregues: 14, falharam: 2, verificadas: 16, percentual: 88 });
checar('seq novo reabre o popup', visivel(), true);
checar('mensagem atualiza para os números novos',
    ['14 de 16', '(88%)'].filter(t => !elementos['entrega-msg'].innerHTML.includes(t)), []);

// --- o botão de parar realmente para --------------------------------------
chamadas.length = 0;
pararPorAlertaDeEntrega();
checar('"Parar o envio" fecha o popup', visivel(), false);
checar('"Parar o envio" chama POST /stop de verdade',
    chamadas.filter(c => c.url === '/stop' && c.method === 'POST').length, 1);

// --- o tom do texto: este aviso NÃO é o de lentidão ------------------------
//
// O popup de lentidão diz explicitamente "o envio continua normalmente — não
// precisa parar". Se esse texto aparecer aqui, o cliente vai ignorar o alarme
// e seguir enviando até a conta ser bloqueada.
const modal = html.split('id="entrega-overlay"')[1].split('</div>\n    </div>')[0];
checar('não diz que o envio continua normalmente',
    /não precisa parar|continua normalmente/i.test(modal), false);
checar('avisa sobre bloqueio da conta', /bloqueio da conta/i.test(modal), true);
checar('recomenda parar', /parar o envio/i.test(modal), true);
checar('tranquiliza sobre retomar de onde parou',
    /segue de onde parou/i.test(modal), true);

console.log(falhas === 0 ? '\nTodos os testes passaram.' : `\n${falhas} teste(s) falharam.`);
process.exit(falhas === 0 ? 0 : 1);
