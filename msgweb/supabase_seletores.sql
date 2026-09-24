-- ============================================================
-- Tabela de seletores do WhatsApp Web
-- ============================================================
-- Consumida por `seletores.py`. Publicar um seletor novo aqui conserta todos
-- os clientes sem build nem release -- e sem o usuario fazer nada.
--
-- COMO USAR: cole no SQL Editor do Supabase e execute uma vez.
-- Nada disto e obrigatorio: sem a tabela, o app usa os seletores embutidos
-- no .exe e funciona normalmente. Isto so liga a camada de atualizacao.
--
-- Versao do schema esperada pelo app: 1
-- ============================================================

create table if not exists public.seletores (
    id             bigint generated always as identity primary key,
    versao_schema  integer     not null,
    -- Rotulo livre da publicacao, so para diagnostico ("2026-09-07.1").
    versao         text,
    -- O app pega a linha ativa mais recente para o seu versao_schema.
    -- Desativar a linha ruim faz rollback sem apagar historico.
    ativo          boolean     not null default true,
    criado_em      timestamptz not null default now(),
    -- Objeto { "chave_do_seletor": "string css" }. Algumas chaves sao
    -- LISTAS de strings, tentadas em ordem (botao de anexar, botao de
    -- enviar, campo de legenda, canvas do QR) -- o tipo de cada chave e
    -- fixado pelo embutido e o payload nao pode troca-lo.
    -- Chave desconhecida, tipo trocado, string vazia, string acima de 500
    -- caracteres ou lista com mais de 30 itens sao descartados por
    -- `_validar_payload()` no cliente.
    seletores      jsonb       not null
);

-- O app busca com: versao_schema=eq.N & ativo=is.true & order=criado_em.desc & limit=1
create index if not exists seletores_busca_idx
    on public.seletores (versao_schema, ativo, criado_em desc);


-- ============================================================
-- RLS: anon LE, anon NUNCA ESCREVE
-- ============================================================
-- Isto nao e detalhe de arrumacao, e o ponto central de seguranca:
--
--   A chave anon vai DENTRO do .exe distribuido ao cliente. Ou seja, ela e
--   publica -- qualquer pessoa com o executavel a tem.
--
-- Se anon pudesse escrever, qualquer um poderia publicar seletores para
-- TODOS os clientes de uma vez: apontar a leitura para o elemento errado,
-- quebrar o envio de todo mundo, ou fazer o app ler o que nao deve.
--
-- O `_validar_payload()` do cliente limita o estrago (so string, so chave
-- conhecida, com teto de tamanho), mas ele e a segunda linha de defesa.
-- A primeira e esta policy.
--
-- Escrita so pela service_role (que ignora RLS), a partir da sua maquina.
-- ============================================================

alter table public.seletores enable row level security;

drop policy if exists "seletores: leitura publica" on public.seletores;
create policy "seletores: leitura publica"
    on public.seletores
    for select
    to anon, authenticated
    using (ativo = true);

-- Sem policy de insert/update/delete para anon: sem policy, RLS nega.


-- ============================================================
-- Linha inicial: os embutidos de hoje
-- ============================================================
-- Identica ao `PADRAO` de seletores.py, entao publicar isto nao muda nada no
-- cliente (`atualizar_do_servidor` relata "0 mudanca(s)"). Serve de gabarito:
-- para conserta-la depois, insira uma linha NOVA com o valor corrigido em vez
-- de editar esta -- assim da para desativar e voltar atras.
--
-- Nao e preciso republicar o objeto inteiro para consertar um seletor: o
-- cliente parte sempre do embutido e so sobrepoe as chaves presentes no
-- payload. Uma linha com uma chave so e valida e e o normal.
-- ============================================================

insert into public.seletores (versao_schema, versao, seletores)
values (
    1,
    '2026-09-12.1',
    '{
    "pane_side": "#pane-side",
    "linha_conversa": "#pane-side [role=\"listitem\"], #pane-side [role=\"row\"]",
    "linha_titulo": "[data-testid=\"cell-frame-title\"]",
    "linha_horario": "[data-testid=\"cell-frame-primary-detail\"]",
    "linha_previa": "[data-testid=\"cell-frame-secondary\"]",
    "linha_status_ultima_msg": "[data-testid=\"last-msg-status\"]",
    "linha_simbolo_midia": "[data-testid=\"chat-msg-symbol\"]",
    "linha_nao_lidas": "[data-testid=\"icon-unread-count\"]",
    "busca_input": "input[role=\"textbox\"][aria-label^=\"Pesquisar\"]",
    "busca_container": "[data-testid=\"chat-list-search-container\"]",
    "campo_mensagem": "footer div[contenteditable=''true'']",
    "input_arquivo": "input[type=\"file\"]",
    "modais": "div[role=\"dialog\"], div[data-animate-modal-body=\"true\"], div[data-animate-modal-popup=\"true\"], .overlay",
    "modal_botoes": "div[role=\"dialog\"] button, div[role=\"dialog\"] div[role=\"button\"]",
    "alertas_conexao": "div[role=\"alert\"], [data-testid=\"alert-computer\"], [data-testid=\"alert-phone\"]",
    "area_conversa": "div[data-tab] button, div[data-tab] span, div.copyable-area button, div.copyable-area span",
    "qr_canvas": [
        "canvas[aria-label*=\"QR\"]",
        "canvas[aria-label*=\"qr\"]",
        "div[data-ref] canvas",
        "[data-testid=\"qrcode\"]"
    ],
    "botao_anexar": [
        "button[aria-label=\"Anexar\"]",
        "button[aria-label=\"Attach\"]",
        "span[data-icon=\"plus-rounded\"]",
        "span[data-icon=\"plus\"]",
        "span[data-icon=\"clip\"]",
        "span[data-icon=\"attach-menu-plus\"]",
        "[data-testid=\"clip\"]"
    ],
    "botao_enviar_modal": [
        "[data-testid=\"send\"]",
        "span[data-icon=\"wds-ic-send-filled\"]",
        "span[data-icon=\"send\"]",
        "span[data-icon=\"send-light\"]",
        "div[role=\"button\"][aria-label*=\"Enviar\"]",
        "div[role=\"button\"][aria-label*=\"Send\"]",
        "button[aria-label=\"Enviar\"]",
        "button[aria-label=\"Send\"]"
    ],
    "campo_legenda_presenca": [
        "div[contenteditable=\"true\"][aria-label*=\"legenda\"]",
        "div[contenteditable=\"true\"][aria-label*=\"caption\"]",
        "div[data-testid=\"media-caption-input-container\"]",
        "div[role=\"dialog\"] div[contenteditable=\"true\"]"
    ],
    "campo_legenda_edicao": [
        "div[contenteditable=\"true\"][data-testid=\"media-caption-input-container\"]",
        "div.copyable-text[contenteditable=\"true\"][data-tab]",
        "div[role=\"dialog\"] div[contenteditable=\"true\"]",
        "div.overlay div[contenteditable=\"true\"]"
    ],
    "icone_tique_duplo": "wds-ic-read",
    "icone_falha": "message-fail"
}'::jsonb
);
