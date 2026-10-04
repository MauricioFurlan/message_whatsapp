// Painel do log embaixo: auto-scroll que respeita a leitura, e o painel oculto.
//
// 1. Auto-scroll como o do DevTools: uma linha nova só leva ao fim quem já
//    estava no fim. Antes toda linha fazia scrollTop = scrollHeight, e quem
//    rolava para cima para ler algo era puxado de volta na linha seguinte —
//    durante um envio, o log ficava ilegível.
// 2. Linhas velhas saindo do topo (limite de 200) não podem fazer o texto de
//    quem está lendo escorregar.
// 3. Com o painel oculto, linhas novas viram um contador "N novas"; uma linha
//    🚫 (ação necessária, sem ela o envio não anda) reabre o painel; e o
//    histórico restaurado ao recarregar a página não conta como novidade.
//
// Uso:  node tests/test_painel_log_ui.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const raiz = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(raiz, 'static', 'index.html'), 'utf8');
const src = html.split('<script>')[1].split('</script>')[0];

const ALTURA_LINHA = 16;

function classList() {
    return {
        _set: new Set(),
        add(c) { this._set.add(c); },
        remove(c) { this._set.delete(c); },
        toggle(c, on) { if (on === undefined) on = !this._set.has(c); on ? this._set.add(c) : this._set.delete(c); },
        contains(c) { return this._set.has(c); },
    };
}

function stubEl() {
    return {
        value: '', innerHTML: '', textContent: '', title: '', placeholder: '',
        checked: false, disabled: false, style: {}, files: [], dataset: {},
        classList: classList(),
        addEventListener() {}, querySelector: () => null,
        querySelectorAll: () => [], insertAdjacentHTML() {}, remove() {}, focus() {},
        closest: () => null, appendChild() {}, removeChild() {}, children: [],
        getBoundingClientRect: () => ({ top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }),
    };
}

// Área de log com geometria: cada linha mede ALTURA_LINHA, a janela visível
// mede `clientHeight`, e scrollTop fica preso entre 0 e o máximo, como no DOM.
function novaLogArea(clientHeight) {
    const area = {
        children: [], clientHeight, style: {}, classList: classList(),
        get innerHTML() { return ''; },
        set innerHTML(v) { this.children = []; },
        _scrollTop: 0,
        querySelector: () => null,
        get scrollHeight() { return this.children.length * ALTURA_LINHA; },
        get scrollTop() { return this._scrollTop; },
        set scrollTop(v) {
            const max = Math.max(0, this.scrollHeight - this.clientHeight);
            this._scrollTop = Math.min(max, Math.max(0, v));
        },
        appendChild(el) { this.children.push(el); },
        removeChild(el) { this.children = this.children.filter(c => c !== el); },
        get firstChild() { return this.children[0]; },
    };
    return area;
}

let logArea = novaLogArea(160);
const elementos = {
    'log-resizer': stubEl(), 'log-toggle-seta': stubEl(),
    'log-toggle-texto': stubEl(), 'log-novas': stubEl(),
};
const guardado = {};

const sandbox = {
    console: { log: () => {}, warn: () => {}, error: () => {} },
    localStorage: {
        getItem: (k) => (k in guardado ? guardado[k] : null),
        setItem(k, v) { guardado[k] = String(v); },
        removeItem(k) { delete guardado[k]; },
    },
    document: {
        getElementById: (id) => (id === 'log-area' ? logArea : (elementos[id] || stubEl())),
        addEventListener() {},
        createElement: () => ({ className: '', title: '', textContent: '', offsetHeight: ALTURA_LINHA }),
        querySelectorAll: () => [],
        activeElement: null,
    },
    window: { innerHeight: 800, addEventListener() {} },
    fetch: () => Promise.resolve({ ok: true, json: () => ({}) }),
    EventSource: function () { return { close() {}, addEventListener() {} }; },
    setTimeout, Number, String, Math, JSON, parseInt, RegExp,
};

vm.runInNewContext(src, sandbox);

const { addLogEntry, restoreLogsFromServer, alternarPainelLog, setupPainelLog } = sandbox;
for (const [nome, fn] of Object.entries({ addLogEntry, restoreLogsFromServer, alternarPainelLog, setupPainelLog })) {
    if (typeof fn !== 'function') throw new Error(`${nome} não encontrada em static/index.html`);
}

let falhas = 0;
function checar(titulo, obtido, esperado) {
    const ok = JSON.stringify(obtido) === JSON.stringify(esperado);
    if (!ok) falhas++;
    console.log(`${ok ? 'PASSOU' : 'FALHOU'}  ${titulo}`);
    if (!ok) console.log(`   obtido: ${JSON.stringify(obtido)}   esperado: ${JSON.stringify(esperado)}`);
}

function noFim() { return logArea.scrollTop === Math.max(0, logArea.scrollHeight - logArea.clientHeight); }
function linhas(n, prefixo) { for (let i = 0; i < n; i++) addLogEntry(`[10:00:00] ${prefixo} ${i}`); }
function novas() {
    const el = elementos['log-novas'];
    return el.classList.contains('hidden') ? null : el.textContent;
}

setupPainelLog();

// --- 1. auto-scroll --------------------------------------------------------
linhas(30, 'linha');
checar('no fim: linha nova leva ao fim', noFim(), true);

logArea.scrollTop = 100;  // usuário rolou para cima para ler
linhas(5, 'durante a leitura');
checar('lendo lá em cima: linha nova NÃO puxa para o fim', logArea.scrollTop, 100);

logArea.scrollTop = logArea.scrollHeight;  // voltou ao fim por conta própria
linhas(1, 'depois');
checar('de volta ao fim: volta a acompanhar', noFim(), true);

logArea.scrollTop = logArea.scrollHeight - logArea.clientHeight - 10;  // quase no fim
linhas(1, 'quase');
checar('a poucos px do fim conta como fim', noFim(), true);

// --- 2. limite de 200 sem escorregar ---------------------------------------
logArea = novaLogArea(160);
linhas(200, 'cheio');
logArea.scrollTop = 800;
const primeiraVisivel = Math.floor(logArea.scrollTop / ALTURA_LINHA);
const textoLido = logArea.children[primeiraVisivel].textContent;
linhas(3, 'transborda');
checar('continua no limite de 200 linhas', logArea.children.length, 200);
checar('quem está lendo continua vendo a mesma linha',
    logArea.children[Math.floor(logArea.scrollTop / ALTURA_LINHA)].textContent, textoLido);

// --- 3. painel oculto ------------------------------------------------------
logArea = novaLogArea(160);
alternarPainelLog(false);
checar('ocultar: área do log some', logArea.classList.contains('hidden'), true);
checar('ocultar: preferência salva', JSON.parse(guardado.log_painel).aberto, false);
checar('ocultar sem linhas novas: sem contador', novas(), null);

linhas(1, 'oculta');
checar('oculto: 1 linha nova', novas(), '1 nova');
linhas(2, 'oculta');
checar('oculto: 3 linhas novas', novas(), '3 novas');

restoreLogsFromServer(['[10:00:00] velha 1', '[10:00:00] 🚫 velha que pedia ação']);
checar('histórico restaurado não conta como novidade', novas(), '3 novas');
checar('nem reabre o painel por um 🚫 antigo', logArea.classList.contains('hidden'), true);

alternarPainelLog();
checar('mostrar: área volta', logArea.classList.contains('hidden'), false);
checar('mostrar: contador zera', novas(), null);
checar('mostrar: abre no mais recente', noFim(), true);

alternarPainelLog(false);
linhas(2, 'oculta');
addLogEntry('[10:00:00] 🚫 Feche a janela do Chrome que está usando o perfil');
checar('linha 🚫 reabre o painel sozinha', logArea.classList.contains('hidden'), false);
checar('e a preferência passa a ser aberto', JSON.parse(guardado.log_painel).aberto, true);

// O pedido de QR também trava o envio até o usuário agir: com o log oculto
// ele ficava invisível. É o backend que o escreve, e só com um QR na tela.
alternarPainelLog(false);
addLogEntry('[10:00:00] ⏳ Escaneie o QR Code no navegador para conectar seu WhatsApp...');
checar('pedido de QR Code reabre o painel sozinho', logArea.classList.contains('hidden'), false);

// A confirmação do botão Iniciar não pode afirmar "escaneie o QR": com a
// sessão já ativa não há QR nenhum. Quem pede o QR é o log, quando há um.
const confirmacaoInicio = html.match(/'Envio iniciado[^']*'/);
checar('confirmação do Iniciar existe', !!confirmacaoInicio, true);
checar('confirmação do Iniciar não fala em QR Code',
    !!confirmacaoInicio && /QR/i.test(confirmacaoInicio[0]), false);

// "Parada solicitada..." some quando a parada termina (nada mais rodando);
// enquanto ainda está parando, fica. Um erro no mesmo lugar não é apagado.
{
    const controle = stubEl();
    elementos['control-status'] = controle;
    const st = (state) => ({ state, progress: {}, logs: [] });
    const tentar = (titulo, fn) => {
        try { fn(); } catch (e) { falhas++; console.log(`FALHOU  ${titulo}: ${e.message}`); }
    };
    // Os "..." são CSS (::after de .em-andamento), não texto.
    checar('stopSending marca a mensagem de parada como em andamento',
        /'Parada solicitada[^']*'[\s\S]{0,200}em-andamento/.test(html), true);
    controle.textContent = 'Parada solicitada. Finalizando envio atual';
    controle.classList.add('em-andamento');
    tentar('updateDashboard enviando', () => sandbox.updateDashboard(st('enviando')));
    checar('ainda enviando: mensagem de parada fica', controle.textContent,
        'Parada solicitada. Finalizando envio atual');
    checar('ainda enviando: pontinhos seguem animando', controle.classList.contains('em-andamento'), true);
    tentar('updateDashboard parado', () => sandbox.updateDashboard(st('parado')));
    checar('parada concluída: mensagem some', controle.textContent, '');
    checar('parada concluída: pontinhos param (senão animam numa linha vazia)',
        controle.classList.contains('em-andamento'), false);

    controle.textContent = 'Erro: licença inválida';
    tentar('updateDashboard parado (erro)', () => sandbox.updateDashboard(st('parado')));
    checar('erro no mesmo lugar não é apagado', controle.textContent, 'Erro: licença inválida');
    delete elementos['control-status'];
}

// --- preferência sobrevive a recarregar ------------------------------------
guardado.log_painel = JSON.stringify({ aberto: false, altura: 333 });
setupPainelLog();
checar('recarregar: volta oculto', logArea.classList.contains('hidden'), true);
checar('recarregar: volta com a altura salva', logArea.style.height, '333px');

guardado.log_painel = JSON.stringify({ aberto: true, altura: 5000 });
setupPainelLog();
checar('altura salva maior que 70% da janela é limitada', logArea.style.height, '560px');

guardado.log_painel = '{lixo';
setupPainelLog();
checar('preferência corrompida não quebra a página', typeof logArea.style.height, 'string');

console.log(falhas === 0 ? '\nTudo passou.' : `\n${falhas} falha(s).`);
process.exit(falhas === 0 ? 0 : 1);
