// Regressão: identificação do contato no evento SSE contact_update.
//
// Bug corrigido: o backend identificava o contato pelo NÚMERO e o frontend
// marcava toda linha que "casasse" por sufixo. Consequências:
//   - número repetido em várias linhas -> todas viravam "Enviado" de uma vez
//   - linha com número vazio -> rowNum.endsWith('') é sempre true em JS,
//     então UM contato inválido sem telefone marcava a tabela inteira como
//     "Inválido", e o save seguinte gravava isso na planilha.
//
// Agora o contato é identificado por row_index (índice da linha na planilha).
//
// Uso:  node tests/test_contact_update.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const raiz = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(raiz, 'static', 'index.html'), 'utf8');
const src = html.split('<script>')[1].split('</script>')[0];

// --- DOM falso: só o suficiente para o script carregar e a função rodar -----
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

function fakeRow(numero, enviado = false, invalido = false, pessoa = 'Contato') {
    const cells = {
        '.contact-numero': { value: numero },
        '.contact-pessoa': { value: pessoa },
        '.contact-status': { innerHTML: '' },
        '.contact-data': { textContent: '' },
        '.contact-reset': { classList: { remove() {}, add() {} } },
        '.contact-row-num': { textContent: '' },
    };
    const row = {
        dataset: { enviado: enviado ? '1' : '0', invalido: invalido ? '1' : '0', dataEnvio: '' },
        querySelector: (sel) => cells[sel] || stubEl(),
        _removida: false,
        remove() { this._removida = true; },
    };
    return row;
}

let linhas = [];
const visiveis = () => linhas.filter(l => !l._removida);
const sandbox = {
    console: { log: () => {}, warn: () => {}, error: () => {} },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: {
        getElementById: () => stubEl(),
        addEventListener() {},
        createElement: () => stubEl(),
        querySelectorAll: (sel) => (sel === '#contacts-tbody tr' ? visiveis() : []),
        activeElement: null,
    },
    window: {}, fetch: () => Promise.resolve({ ok: true, json: () => ({}) }),
    EventSource: function () { return { close() {}, addEventListener() {} }; },
    setTimeout, Number, String, Math, JSON,
};

// Rodar o script inteiro também garante que o index.html não tem erro de sintaxe
vm.runInNewContext(src, sandbox);

const { updateContactRowStatus } = sandbox;
if (typeof updateContactRowStatus !== 'function') {
    throw new Error('updateContactRowStatus não encontrada em static/index.html');
}

// --- Cenários --------------------------------------------------------------
function estado() {
    return visiveis().map(l => {
        if (l.dataset.invalido === '1') return 'Invalido';
        if (l.dataset.enviado === '1') return 'Enviado';
        return 'Pendente';
    });
}

let falhas = 0;

function cenario(titulo, montarLinhas, evento, esperado) {
    linhas = montarLinhas();
    updateContactRowStatus(evento.row_index, evento.numero, evento.status, evento.data_envio || '');
    const obtido = estado();
    const ok = JSON.stringify(obtido) === JSON.stringify(esperado);
    if (!ok) falhas++;
    console.log(`${ok ? 'PASSOU' : 'FALHOU'}  ${titulo}`);
    if (!ok) {
        console.log(`   evento:   row_index=${evento.row_index} numero=${JSON.stringify(evento.numero)} status=${evento.status}`);
        console.log(`   obtido:   ${obtido.join(' | ')}`);
        console.log(`   esperado: ${esperado.join(' | ')}`);
    }
}

function checarIgual(titulo, obtido, esperado) {
    const ok = obtido === esperado;
    if (!ok) falhas++;
    console.log(`${ok ? 'PASSOU' : 'FALHOU'}  ${titulo}`);
    if (!ok) console.log(`   obtido: ${obtido}   esperado: ${esperado}`);
}

const tabelaComVazia = () => [
    fakeRow('(19)99422-9146'), fakeRow('(11)98888-7777'),
    fakeRow('(21)97777-6666'), fakeRow(''), fakeRow('(11)3322-4455'),
];
const tabelaDuplicada = () => [
    fakeRow('(19)99422-9146'), fakeRow('(11)98888-7777'),
    fakeRow('(19)99422-9146'), fakeRow('(19)99422-9146'),
];

cenario('linha sem número marcada inválida não contamina as outras',
    tabelaComVazia, { row_index: 3, numero: '', status: 'invalido' },
    ['Pendente', 'Pendente', 'Pendente', 'Invalido', 'Pendente']);

cenario('número repetido: apenas a linha enviada vira Enviado',
    tabelaDuplicada, { row_index: 0, numero: '19994229146', status: 'enviado', data_envio: '2026-08-05 22:30:00' },
    ['Enviado', 'Pendente', 'Pendente', 'Pendente']);

cenario('número repetido: a terceira ocorrência é independente',
    tabelaDuplicada, { row_index: 3, numero: '19994229146', status: 'enviado', data_envio: '2026-08-05 22:31:00' },
    ['Pendente', 'Pendente', 'Pendente', 'Enviado']);

cenario('evento válido não marca a linha de número vazio',
    tabelaComVazia, { row_index: 0, numero: '19994229146', status: 'enviado', data_envio: '2026-08-05 22:32:00' },
    ['Enviado', 'Pendente', 'Pendente', 'Pendente', 'Pendente']);

cenario('número curto (999) não casa por sufixo com 5511999990999',
    () => [fakeRow('5511999990999'), fakeRow('(11)98888-7777')],
    { row_index: 1, numero: '999', status: 'invalido' },
    ['Pendente', 'Invalido']);

cenario('índice fora de faixa com número único: usa o fallback por número',
    tabelaComVazia, { row_index: 99, numero: '11988887777', status: 'enviado', data_envio: '2026-08-05 22:33:00' },
    ['Pendente', 'Enviado', 'Pendente', 'Pendente', 'Pendente']);

cenario('índice fora de faixa com número ambíguo: ignora em vez de corromper',
    tabelaDuplicada, { row_index: 99, numero: '19994229146', status: 'enviado' },
    ['Pendente', 'Pendente', 'Pendente', 'Pendente']);

cenario('índice aponta para número diferente: não marca a linha errada',
    tabelaComVazia, { row_index: 0, numero: '11988887777', status: 'enviado', data_envio: '2026-08-05 22:34:00' },
    ['Pendente', 'Enviado', 'Pendente', 'Pendente', 'Pendente']);

// --- Alinhamento tabela x planilha -----------------------------------------
// O backend descarta linhas sem nome E sem número ao salvar. Se a tabela
// continuasse mostrando essas linhas, todos os índices abaixo delas ficariam
// deslocados em relação à planilha.
const { dropEmptyContactRows } = sandbox;
if (typeof dropEmptyContactRows !== 'function') {
    throw new Error('dropEmptyContactRows não encontrada em static/index.html');
}

linhas = [
    fakeRow('(19)99422-9146', false, false, 'Ana'),
    fakeRow('', false, false, ''),                      // linha totalmente vazia
    fakeRow('(11)98888-7777', false, false, 'Bruno'),
    fakeRow('', false, false, 'Carla sem numero'),      // tem nome: o backend mantém
];
const removidas = dropEmptyContactRows();
checarIgual('linha totalmente vazia é descartada antes de salvar', removidas, 1);
checarIgual('linha com nome e sem número é mantida', visiveis().length, 3);

// Depois do alinhamento, o índice 1 (Bruno na planilha) aponta para Bruno na tabela
updateContactRowStatus(1, '11988887777', 'enviado', '2026-08-05 22:35:00');
checarIgual('índice pós-alinhamento acerta a linha', estado().join('|'), 'Pendente|Enviado|Pendente');

console.log(falhas === 0 ? '\nOK: todos os cenários passaram.' : `\nFALHA: ${falhas} cenário(s).`);
process.exit(falhas === 0 ? 0 : 1);
