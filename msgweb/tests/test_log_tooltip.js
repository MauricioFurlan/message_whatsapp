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

// Elemento mínimo: a linha do log agora é montada com <span>s filhos
// (horário | marcador | texto), e textContent junta os filhos como no DOM.
function novoElemento(extra) {
    return Object.assign({
        className: '', title: '', children: [], _texto: '',
        appendChild(c) { this.children.push(c); return c; },
        get textContent() { return this._texto + this.children.map(c => c.textContent).join(''); },
        set textContent(v) { this._texto = String(v); this.children = []; },
    }, extra || {});
}

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
        createElement: () => novoElemento(),
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
// Não existe mais retentativa: toda falha marca o contato como inválido na hora,
// com o motivo no tooltip para o usuário investigar.
problema('falha no anexo diz que o texto não foi enviado',
    '❌ Ana (11999998888) — falha no anexo: arquivo não encontrado. Mensagem NÃO enviada, contato marcado como inválido.',
    'log-giveup', ['anexo falhou', 'NÃO foi enviada', 'reenviar']);

problema('timeout ao abrir a conversa explica as causas possíveis',
    '❌ Ana (11999998888) — timeout ao abrir a conversa, marcado como inválido. Passe o mouse no status do contato para ver o motivo.',
    'log-nowhats', ['não abriu no WhatsApp', 'sem conta no WhatsApp', 'reenviar']);

problema('erro inesperado aponta o arquivo de log',
    '⚠️ Ana (11999998888) — erro inesperado: Message: element not interactable',
    'log-tech', ['arquivo de log', 'marcado como inválido']);

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
const cores = ['log-sheet', 'log-nowhats', 'log-giveup', 'log-tech', 'log-skipped'];
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
checar('linha de sucesso sai como sucesso e sem tooltip',
    sucesso.className.includes('log-sucesso') && sucesso.title === '',
    `className: ${sucesso.className} title: ${sucesso.title}`);
checar('linha [SKIP] inválida sai em cinza, não no amarelo genérico',
    skip.className.includes('log-skipped') && !skip.className.includes('text-yellow-400'),
    `className: ${skip.className}`);

// --- Na tela, o emoji vira marcador de nível -------------------------------
// O backend (e o log.txt) continua com os emojis; só a exibição troca. A
// classificação lê a linha original, então o 🚫 segue valendo para
// linhaPedeAcao mesmo sumindo da tela.
function linha(mensagem) {
    logArea.children = [];
    addLogEntry(mensagem);
    const el = logArea.children[0];
    const [ts, marca, texto] = el.children.map(c => c.textContent);
    return { classe: el.className, ts, marca, texto };
}
function nivel(titulo, mensagem, classe, marca) {
    const l = linha(mensagem);
    checar(titulo, l.classe.includes(classe) && l.marca === marca,
        `className: ${l.classe} marca: ${l.marca} (esperado ${classe} / ${marca})`);
}

const ok = linha('[14:50:31] ✅ Bruno — mensagem enviada com sucesso.');
checar('horário vai para a coluna própria, sem colchetes', ok.ts === '14:50:31', `ts: ${ok.ts}`);
checar('o emoji do começo some do texto', ok.texto === 'Bruno — mensagem enviada com sucesso.', `texto: ${ok.texto}`);
checar('nenhum emoji sobra no texto exibido',
    !/\p{Extended_Pictographic}/u.test(linha('[10:00:00] ⏸️ Pausa de ~4.0 min antes da próxima leva').texto));
checar('emoji no MEIO da linha é do conteúdo e fica',
    linha('[10:00:00] Ana respondeu: oi 👋').texto === 'Ana respondeu: oi 👋');
checar('linha sem horário não quebra', linha('Envio iniciado. Abrindo navegador...').ts === '');

nivel('✅ é sucesso', '[10:00:00] ✅ Sessão ativa detectada!', 'log-sucesso', '✓');
nivel('🎉 é sucesso', '[10:00:00] 🎉 Envio finalizado! Total enviado: 3 mensagens', 'log-sucesso', '✓');
nivel('⚠️ comum é aviso', '[10:00:00] ⚠️ O WhatsApp Web continua lento.', 'log-aviso', '▲');
nivel('🔄 retentativa é aviso', '[10:00:00] 🔄 Ana — conversa não abriu, tentando novamente', 'log-aviso', '▲');
nivel('🛑 do Parar é aviso', '[10:00:00] 🛑 Envio interrompido pelo usuário.', 'log-aviso', '▲');
nivel('🛑 do navegador caído é erro', '[10:00:00] 🛑 O navegador foi fechado ou perdeu a conexão. Envio abortado.', 'log-erro', '✕');
nivel('ERRO é erro', '[10:00:00] ERRO: Não foi possível iniciar o Chrome: x', 'log-erro', '✕');
nivel('⏳ é espera', '[10:00:00] ⏳ Aguardando o WhatsApp Web carregar as conversas...', 'log-espera', '…');
nivel('🚫 é ação', '[10:00:00] 🚫 Feche a janela do Chrome e clique em Iniciar novamente.', 'log-acao', '!');
nivel('pedido de QR Code é ação (trava o envio)', '[10:00:00] ⏳ Escaneie o QR Code no navegador para conectar seu WhatsApp...', 'log-acao', '!');
nivel('início de leva', '[10:00:00] ▶️ Executando leva 1 de 3: envia 4 mensagens', 'log-leva', '▸');
nivel('linha comum é neutra, não verde', '[10:00:00] Fechando navegador...', 'log-info', '·');
nivel('problema de contato leva ✕ na cor do motivo',
    '[10:00:00] ❌ Ana (999) — número inválido, marcado como inválido (pulado sem abrir o WhatsApp).', 'log-sheet', '✕');

const niveis = ['log-info', 'log-espera', 'log-sucesso', 'log-aviso', 'log-erro', 'log-acao', 'log-leva', 'log-pulado'];
const semRegra = niveis.filter(c => !new RegExp(`\\.${c}\\s*\\{[^}]*color:`).test(css));
checar('todo nível tem cor no CSS', semRegra.length === 0, `sem regra: ${semRegra.join(', ')}`);

console.log(falhas === 0 ? '\nOK: todos os cenários passaram.' : `\nFALHA: ${falhas} cenário(s).`);
process.exit(falhas === 0 ? 0 : 1);
