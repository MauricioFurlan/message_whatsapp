 3. Servidor sem autenticação em 0.0.0.0:8000 (launcher.py:51, app.py:720)
 Qualquer máquina da rede local acessa /upload, /start, /download-contacts e /download-log sem credencial — inclui
  baixar a base de contatos e disparar envios. Se não há uso remoto intencional, troque para 127.0.0.1:8000.

 5. Números corrompidos no editor de contatos (app.py:457)

  Reproduzi isto: quando a coluna Número tem qualquer célula vazia, o pandas lê como float64, e o astype(str) do
  /contacts devolve "19994229146.0". O formatPhone do frontend remove o ponto e sobra 199942291460 (12 dígitos, com um 0
   extra). Pior: 1133224455.0 → 11332244550, que tem 11 dígitos e é exibido como um celular válido (11)33224-4550. Ao
  salvar o editor, o número errado é gravado na planilha. O envio em si está protegido (_clean_number), mas o editor não
  — falta aplicar a mesma normalização no /contacts.

  6. Números com DDD 55 perdem o código do país (whatsapp_sender.py:438)

  if not numero_limpo.startswith("55") — um celular do RS como 55987654321 (DDD 55) já começa com "55", então nada é
  prefixado e o WhatsApp interpreta como país 55 + 987654321. Destinatário errado ou inválido. O critério deve ser o
  comprimento (10/11 dígitos = falta DDI), não o prefixo.

  7. TimeoutException é tratado sempre como "número inválido" (whatsapp_sender.py:515, 830)

  Qualquer lentidão de rede, queda de sessão ou logout do WhatsApp gera timeout, e o contato é marcado Invalido="X"
  permanentemente. Se a sessão cair no meio de uma rodada, todos os contatos seguintes são queimados em sequência. Falta
  distinguir "chat não existe" de "página não carregou" e abortar quando o driver/sessão morre (o WebDriverException
  está importado mas nunca usado).

  8. Mensagem duplicada se o Excel estiver aberto (whatsapp_sender.py:~800)

  Após enviar com sucesso, _save_contacts(df) grava a planilha. Se ela estiver aberta no Excel, o to_excel levanta
  PermissionError, cai no except Exception genérico e o contato não é marcado como enviado — na próxima rodada recebe a
  mensagem de novo. Vale gravar com retry/arquivo temporário e nunca perder a marcação.

  9. Compensação de rodadas sem limite (whatsapp_sender.py:874)

  compensacao = (msgs_por_rodada - enviados_rodada) + compensacao acumula todo contato inválido/falho. Depois de algumas
  rodadas ruins, batch_size explode e uma única rodada tenta disparar dezenas de mensagens seguidas — exatamente o
  padrão que gera bloqueio. Precisa de teto (ex.: min(compensacao, msgs_por_rodada)).

  10. /upload destrói a planilha antes de validar (app.py:232 e 302)

  O arquivo é escrito em uploads/contatos.xlsx antes da checagem de colunas; se faltar coluna, o os.remove apaga tudo e
  a planilha anterior (com o progresso de Enviado/DataEnvio) é perdida. Além disso, /upload e /upload-media não são
  bloqueados durante o envio, diferente do /contacts POST — subir uma planilha com o envio rodando corrompe o progresso,
  porque a thread do sender segue gravando em cima.

  Médio

  11. Janela noturna nunca envia (whatsapp_sender.py:_is_business_hours)

  A comparação inicio_min <= agora < fim_min não trata janelas que cruzam a meia-noite (22:00–06:00): o estado fica
  "pausado" para sempre, sem aviso. O frontend tem o mesmo problema (janelaDiariaMin = 0).

  12. Corrida no /start (app.py:414)

  is_running() só retorna True depois que a thread começa. Dois cliques rápidos (ou duas abas) criam dois WhatsAppSender
   com o mesmo --user-data-dir, e o taskkill /F /IM chromedriver.exe do segundo mata o driver do primeiro. Falta um
  lock/flag setado no próprio handler.

  13. taskkill global de chromedriver.exe

  Mata qualquer chromedriver da máquina, inclusive de outros programas/testes do usuário.

  14. KeyError se as colunas mudarem (whatsapp_sender.py:start)

  _load_contacts garante só as colunas de controle; row["Nome"], row["Número"] e row["Mensagem"] não são validados. Uma
  planilha editada à mão derruba a thread com "ERRO FATAL". Note que o README ainda documenta a coluna como Pessoa,
  enquanto o código exige Nome.

  15. /session-status pode dar 500 e é lento (app.py:650)

  max(...) sobre generator vazio levanta ValueError se chrome_profile/ existir só com subpastas vazias. E o rglob("*")
   varre o perfil inteiro do Chrome (milhares de arquivos, dentro do OneDrive) a cada carregamento da página.

  16. Mídia ignorada em silêncio (whatsapp_sender.py:_send_message)

  Caminhos em Arquivo que não passam por os.path.isfile são descartados sem nenhum log — o contato recebe só o texto e o
  usuário acha que o anexo foi enviado. Também vale notar que .mp3/.ogg/.opus são enviados como documento (o _send_media
   força documento para não virar figurinha), então nunca chegam como áudio/voz, apesar de a UI aceitar esses formatos.

  17. escapeHtml não escapa aspas (index.html:571)

  Ela é usada dentro de atributos (value="${escapeHtml(...)}", title="..."). Um nome ou mensagem com " quebra o atributo
  e permite injeção de HTML/handlers na própria tabela. Use replace(/"/g,'&quot;') também, ou monte os nós via
  DOM/textContent.

  18. Match de número no SSE é frouxo (index.html:734)

  numLimpo.endsWith(rowNum) || rowNum.endsWith(numLimpo) — uma linha com número vazio faz endsWith("") retornar true e é
  marcada como enviada; números que terminam igual marcam a linha errada. Compare os últimos 10–11 dígitos exigindo
  tamanho mínimo.

  19. TypeError ao anexar mídia (index.html:1154)

  querySelectorAll('td')[3] é a célula do telefone (a de arquivo é a [5]), que não tem button → querySelector(...)
   retorna null e o .classList estoura. O botão "✕" de remover anexo nunca aparece e o _mediaTargetRow não é
  limpo.
  20. Flood de log em planilhas grandes (whatsapp_sender.py, loop de rodada)

  Um [SKIP] por contato já enviado, em toda rodada: com 1000 enviados são 1000 linhas por rodada no SSE e no log.txt, e
  o buffer de 500 linhas em memória descarta as mensagens úteis. Melhor logar o agregado ("980 já enviados, pulados").