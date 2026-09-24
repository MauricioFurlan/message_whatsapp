"""
Varredura de respostas: descobrir quem respondeu, sem abrir conversa nenhuma.

É a feature #7 do BRAINSTORM_IA.md. O usuário dispara a campanha, e horas ou
dias depois clica em "Verificar respostas": o app abre o Chrome, lê a lista de
conversas, grava o resultado na planilha e fecha.

## Por que uma varredura sob demanda, e não vigilância contínua

O app é fire-and-forget: `_cleanup()` fecha o navegador quando a thread de
envio acaba. Deixar um Chrome de pé vigiando teria três problemas — só
funcionaria com o programa aberto (e as respostas chegam à noite), daria um
quarto significado a `is_running()`, e um driver parado segurando o
`chrome_profile/` faria o próximo `/start` cair em `ChromeProfileInUseError`.

O ponto de fundo é que **a informação não é perecível**: a resposta fica na
conversa esperando. Não é preciso assistir na hora em que ela chega — é preciso
passar lá depois.

## Escopo: a planilha atual, sem recorte por data

O app opera sempre em `uploads/contatos.xlsx` e todo `/upload` sobrescreve,
então a planilha *já é* o recorte da campanha. O escopo é simplesmente as
linhas com `Enviado=X`. Não há configuração de "últimos N dias" — seria um
número arbitrário para um usuário leigo errar.

Contatos **inválidos ficam de fora por construção**, e isso importa: um
inválido nunca teve entrega (`AttachmentError` não manda o texto,
`WhatsAppNotLoadedError` é anterior a qualquer entrega), e se o cliente já
tinha conversa anterior com aquele número, ler a linha atribuiria a esta
campanha o estado de uma mensagem antiga.

## Duas passadas, e a primeira é de graça

1. **Livre:** um `execute_script` lê tudo que já está renderizado no
   `#pane-side` (~71 linhas sem rolar). Custo sub-segundo, e pega a maioria
   quando a campanha foi a última coisa que aconteceu na conta.
2. **Busca:** só para quem sobrou. Digita o número na busca, lê a linha,
   limpa. ~2-3s cada.
3. **Retentativa:** quem não apareceu em nenhuma das duas volta a ser buscado
   uma vez, depois de uma pausa — ver `PAUSA_RETENTATIVA_SEG`.

## Contato salvo na agenda não tem número na linha

A lista mostra o NOME de quem está salvo, e todo o casamento planilha-contra-
lista era pelo número: esses contatos caíam em "não encontrado", o desfecho que
não escreve nada. Na tela isso era um `-`, indistinguível de nunca ter sido
verificado — ou seja, o app não dizia se a mensagem tinha sido vista justamente
para os contatos que o cliente já conhecia.

Dois casamentos de reserva, os dois desenhados para preferir o silêncio à
invenção (`mapa_de_nomes`, `Varredura._casar_por_nome`,
`Varredura._linha_de_contato_salvo`):

- na passada livre, pelo **nome** — e só quando ele identifica um contato só
  dos dois lados, planilha e lista;
- na busca, pela **única conversa que sobrou no filtro** — a lista inteira foi
  filtrada pelo número que digitamos, então o que restou é a conversa dele.

Filtrar pela busca **não abre a conversa nem marca como lida** — o cliente não
perde o badge de não-lidas que usa para trabalhar, e o destinatário não vê
tique azul de uma leitura que não houve.

## "Não encontrei" é o desfecho sem rastro, e por isso tem log próprio

É o único resultado que não escreve NADA na planilha: a linha fica idêntica a
um contato que nunca foi verificado, e a tela mostra o mesmo "-" nos dois
casos. Sem `_log_nao_encontrado()` não sobra evidência de que algo falhou —
diagnosticar uma ocorrência custou seis sondas contra o WhatsApp Web real
(12/09/2026). O log de arquivo registra o número, a volta e o que a busca
devolveu.

## Grava fato, não rótulo

As colunas são `Respondeu` / `DataResposta` / `Entrega` / `UltimaVerificacao`
/ `RespostaTexto`. O rótulo (quente/frio) é derivado na exibição, como o
`duplicado` já é. Rótulo gravado congelaria a régua; derivado, mudar o corte é
mudar uma função pura, sem varrer nada de novo.

`RespostaTexto` é o que torna isso verdade para o eixo que falta. Latência e
entrega saem de metadado, mas quente-contra-morno exige o TEOR — e sem o texto
gravado, mudar essa régua obrigaria a reabrir o Chrome e reler tudo. Com ele,
a triagem (heurística ou LLM) roda offline sobre a planilha.
"""

import logging
import time
from datetime import datetime
from typing import Callable, Optional

import linha_conversa
import seletores
from contact_logic import clean_number

# Mesmo logger de arquivo do resto do app (log.txt), pego pelo nome para não
# importar o whatsapp_sender — que importa este módulo.
file_logger = logging.getLogger("whatsapp_sender_file")

# Valores gravados na coluna Entrega. Deliberadamente em português e legíveis:
# a planilha é aberta no Excel pelo cliente.
ENTREGA_RESPONDEU = "Respondeu"
ENTREGA_LIDO = "Lido"
ENTREGA_ENTREGUE = "Entregue"
ENTREGA_NAO_ENTREGUE = "Não entregue"
ENTREGA_FALHOU = "Falhou"

_DE_ESTADO_PARA_ENTREGA = {
    linha_conversa.ULTIMA_DELES: ENTREGA_RESPONDEU,
    linha_conversa.LIDO: ENTREGA_LIDO,
    linha_conversa.ENTREGUE: ENTREGA_ENTREGUE,
    linha_conversa.NAO_ENTREGUE: ENTREGA_NAO_ENTREGUE,
    linha_conversa.FALHOU: ENTREGA_FALHOU,
}

# Teto do texto da resposta gravado na planilha. O `title` do WhatsApp vem
# inteiro (medido: 393 caracteres), e nada garante um limite lá em cima — mas
# a planilha é aberta no Excel pelo cliente e o texto também trafega inteiro no
# `GET /contacts`. 500 caracteres sobram para qualquer triagem (por `?`, por
# opt-out ou por LLM) e mantêm a célula legível.
LIMITE_RESPOSTA_TEXTO = 500

# Quanto esperar a lista filtrar depois de digitar na busca.
TIMEOUT_BUSCA_SEG = 4.0
INTERVALO_POLL_SEG = 0.2

# Pausa antes de reconsultar quem não foi encontrado na primeira volta.
#
# "Não achei" e "o WhatsApp Web ainda não sincronizou" são a MESMA coisa vistas
# de fora, e a segunda é o caso comum: a varredura abre um Chrome e começa a
# procurar ~15s depois. Caso medido em 12/09/2026 — uma conversa criada pelo
# envio de 5 minutos antes não estava nem na lista renderizada nem no índice da
# busca, e as duas verificações seguidas devolveram "1 não localizada" gastando
# exatamente os 4s de `TIMEOUT_BUSCA_SEG`. A mesma execução mostrava o relógio
# (`ic-schedule`) numa mensagem já enviada: a lista estava fria.
#
# É a lição que `_aquecer_navegacao()` já encoda no envio ("a cold WhatsApp Web
# is the single biggest predictor of failure"), aqui pelo caminho barato: em vez
# de aquecer sempre, só espera quem não foi encontrado. Quem apareceu na passada
# 1 (o caso normal) não paga nada.
PAUSA_RETENTATIVA_SEG = 20.0


def linhas_para_verificar(df) -> list:
    """
    Índices das linhas que a varredura precisa olhar.

    Só `Enviado=X`, e pula quem já foi marcado como tendo respondido: ninguém
    des-responde, então reconsultar é trabalho jogado fora numa varredura que
    já custa ~5 min para 118 contatos.
    """
    alvos = []
    for idx, row in df.iterrows():
        if str(row.get("Enviado", "")).strip().upper() != "X":
            continue
        if str(row.get("Respondeu", "")).strip().lower() == "sim":
            continue
        alvos.append(idx)
    return alvos


def mapa_de_numeros(df, indices) -> dict:
    """
    número normalizado -> [índices]. Uma lista porque a planilha pode repetir
    o mesmo número em linhas diferentes (o duplicado fica inválido, mas a
    original é enviada — e nada impede duas originais legítimas).
    """
    mapa = {}
    for idx in indices:
        num = clean_number(df.at[idx, "Número"])
        if num:
            mapa.setdefault(num, []).append(idx)
    return mapa


def mapa_de_nomes(df, indices) -> dict:
    """
    chave de nome -> número, e SÓ para nomes que identificam um contato só.

    É o casamento de reserva para o contato **salvo na agenda**: a linha dele
    não mostra número nenhum, só o nome, então `mapa_de_numeros` nunca o
    alcança (ver `linha_conversa.titulo_casa_com_nome`).

    Ao contrário do número, nome não é identificador: dois "João" na planilha
    são duas pessoas diferentes e nada na lista de conversas as separa. Um
    nome que aponta para mais de um número é descartado aqui — fica sem
    casamento de reserva, que é exatamente o comportamento de hoje, em vez de
    virar um chute sobre qual dos dois leu a mensagem.
    """
    por_nome = {}
    for idx in indices:
        chave = linha_conversa.chave_de_nome(df.at[idx, "Nome"])
        numero = clean_number(df.at[idx, "Número"])
        if len(chave) < linha_conversa.MIN_CARACTERES_NOME or not numero:
            continue
        por_nome.setdefault(chave, set()).add(numero)
    return {c: next(iter(n)) for c, n in por_nome.items() if len(n) == 1}


def aplicar_leitura(df, idx, leitura: dict, agora: Optional[datetime] = None) -> str:
    """
    Grava numa linha o que a lista de conversas mostrou. Devolve o valor de
    `Entrega` escrito (ou "" se a leitura não era conclusiva).

    `INDETERMINADO` não é gravado: extração quebrada não é evidência, e
    sobrescrever apagaria uma leitura boa anterior.
    """
    estado = leitura.get("estado")
    entrega = _DE_ESTADO_PARA_ENTREGA.get(estado, "")
    if not entrega:
        return ""

    agora = agora or datetime.now()
    respondeu = estado == linha_conversa.ULTIMA_DELES

    df.at[idx, "Entrega"] = entrega
    df.at[idx, "Respondeu"] = "Sim" if respondeu else "Não"
    df.at[idx, "UltimaVerificacao"] = agora.strftime("%Y-%m-%d %H:%M:%S")

    if respondeu:
        # O horário da linha é o da última mensagem — ou seja, o da resposta.
        # Pode vir None (o WhatsApp mostra só o nome do dia da semana em
        # conversas mais antigas), e aí a data fica em branco em vez de
        # inventada: a coluna `Enviado`/`DataEnvio` ainda permite ao cliente
        # saber que respondeu, só não em quanto tempo.
        quando = leitura.get("horario")
        df.at[idx, "DataResposta"] = (
            quando.strftime("%Y-%m-%d %H:%M:%S") if quando else ""
        )
        # O TEOR da resposta — o único eixo de "quente/morno/frio" que não sai
        # de metadado nenhum. Sai de graça: já vem no mesmo `execute_script`
        # que leu o tique. Gravar aqui é o que permite classificar (por
        # heurística hoje, por LLM depois) **sem varrer de novo** — mesma razão
        # de `Entrega` ser fato gravado e o rótulo ser derivado na exibição.
        #
        # SÓ quando respondeu. Quando a última mensagem é nossa, o mesmo campo
        # traz o NOSSO texto (medido na sonda: `'Show'`, `'Eu vim treinar'`),
        # e gravá-lo faria a triagem classificar a nossa própria campanha.
        df.at[idx, "RespostaTexto"] = str(
            leitura.get("ultima_mensagem") or ""
        )[:LIMITE_RESPOSTA_TEXTO]
    else:
        df.at[idx, "DataResposta"] = ""
        df.at[idx, "RespostaTexto"] = ""

    return entrega


# Granularidade do horário que a lista de conversas mostra HOJE: "13:17", sem
# segundos. `interpretar_horario` ancora no segundo 00, então a resposta real
# aconteceu em algum ponto dos 60s daquele minuto — ver `latencia_segundos`.
GRANULARIDADE_HORARIO_SEG = 60


def latencia_segundos(data_envio, data_resposta) -> Optional[float]:
    """
    Quanto tempo o contato levou para responder. None quando não dá para saber.

    Zero é resposta legítima: significa "no mesmo minuto do envio", que a UI
    mostra como "menos de 1 min". Ver o comentário no corpo.

    É o eixo pelo qual a UI ordena — o topo da lista é o "quente". Deliberadamente
    não existe uma função `classificar_quente_morno_frio()`: separar morno de
    quente exige ler o TEOR da resposta (feature #5), e nenhuma regra sobre
    metadado faz isso. "Sim" é a resposta mais quente possível e tem uma
    palavra; "não tenho interesse" tem quatro.
    """
    inicio = _parse_data(data_envio)
    fim = _parse_data(data_resposta)
    if not inicio or not fim:
        return None
    delta = (fim - inicio).total_seconds()
    if delta >= 0:
        return delta

    # Negativo não é viagem no tempo: é imprecisão do horário da linha. Mas há
    # DOIS tamanhos de imprecisão, e tratá-los igual jogava fora o caso mais
    # valioso do produto.
    #
    # **Até um minuto** é a resposta que chegou no MESMO minuto do envio. A
    # linha mostra "13:17" e `interpretar_horario` ancora no segundo 00; se o
    # envio terminou às 13:17:09, a conta dá -9s. A resposta real está entre
    # 13:17:00 e 13:17:59, ou seja a latência verdadeira está entre 0 e ~50s —
    # "menos de um minuto" é uma afirmação PROVADA, não um chute. E é
    # justamente o lead mais quente que cai aqui: quem responde na hora.
    # Devolver None fazia a coluna mostrar só a palavra "Respondeu" exatamente
    # para quem respondeu mais rápido, e mandava esse contato para o fim da
    # ordenação por latência.
    #
    # **Mais que isso** é a âncora de "Ontem" na meia-noite (ou uma data sem
    # hora), onde o erro chega a 24h. Aí continua None: não dá para provar nada.
    if -GRANULARIDADE_HORARIO_SEG < delta < 0:
        return 0.0
    return None


def _parse_data(valor) -> Optional[datetime]:
    texto = str(valor or "").strip()
    if not texto or texto.lower() in ("nan", "none", "nat"):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, fmt)
        except ValueError:
            continue
    return None


class Varredura:
    """
    Orquestra a leitura. Recebe o driver já pronto (com o WhatsApp Web
    carregado) — quem cuida do ciclo de vida do Chrome é o WhatsAppSender, que
    já tem `_init_driver`, detecção de QR e espera de sincronização.
    """

    def __init__(
        self,
        driver,
        log_cb: Optional[Callable] = None,
        stop_cb: Optional[Callable] = None,
        progresso_cb: Optional[Callable] = None,
    ):
        self.driver = driver
        # Quantas CONVERSAS já foram processadas nesta execução. Atributo e não
        # variável local porque a passada de busca virou método próprio (para a
        # retentativa poder reusá-la), e o progresso não pode voltar atrás entre
        # a primeira volta e a segunda.
        self._feitas = 0
        self._log = log_cb or (lambda *_: None)
        self._parar = stop_cb or (lambda: False)
        self._progresso = progresso_cb or (lambda *_a, **_k: None)

    # ---- interação com a busca ----
    def _buscar(self, numero: str) -> list:
        """
        Digita o número na busca e devolve as linhas filtradas.

        A busca do WhatsApp Web é um `<input>` de verdade (não
        `contenteditable`) e fica FORA do `#pane-side`. Filtrar não abre nem
        marca nada como lido — é por isso que a varredura inteira não custa
        nenhuma abertura de conversa.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys

        campo = self.driver.find_element(By.CSS_SELECTOR, seletores.get("busca_input"))
        campo.send_keys(Keys.CONTROL, "a")
        campo.send_keys(Keys.BACKSPACE)
        campo.send_keys(numero)

        alvo = clean_number(numero)
        limite = time.monotonic() + TIMEOUT_BUSCA_SEG
        linhas = []
        anterior = None
        while time.monotonic() < limite:
            if self._parar():
                break
            linhas = linha_conversa.ler_linhas(self.driver)
            if any(l.get("numero") == alvo for l in linhas):
                break
            # Contato SALVO na agenda nunca vai casar pelo número: a linha dele
            # mostra o nome. Sem esta saída, cada um deles paga o
            # `TIMEOUT_BUSCA_SEG` inteiro — 4s por contato, numa varredura que
            # existe para ser barata. Uma única conversa no filtro, idêntica em
            # duas leituras seguidas, é filtragem terminada; a lista ainda
            # encolhendo passa por aqui uma vez só e continua esperando.
            titulos = tuple(
                l.get("titulo") for l in linhas if str(l.get("titulo") or "").strip()
            )
            if len(titulos) == 1 and titulos == anterior:
                break
            anterior = titulos
            time.sleep(INTERVALO_POLL_SEG)

        campo.send_keys(Keys.CONTROL, "a")
        campo.send_keys(Keys.BACKSPACE)
        return linhas

    # ---- execução ----
    def executar(self, df, agora: Optional[datetime] = None) -> dict:
        """
        Varre e grava em `df` (não salva — quem salva é o chamador, que é o
        único dono do arquivo). Devolve um resumo.
        """
        agora = agora or datetime.now()
        alvos = linhas_para_verificar(df)
        mapa = mapa_de_numeros(df, alvos)
        nomes = mapa_de_nomes(df, alvos)
        # `total` conta CONVERSAS a consultar; os contadores do fim contam
        # LINHAS da planilha. Os dois divergem sempre que o mesmo número
        # aparece em várias linhas (o caso normal num teste), e reportar só um
        # deles produzia log absurdo: "verificando 1 contato" seguido de
        # "25 responderam".
        total = len(mapa)
        resumo = {
            "total": total,
            "linhas": len(alvos),
            "verificados": 0,
            "respondeu": 0,
            "nao_entregue": 0,
            "nao_encontrados": 0,
            "interrompida": False,
        }
        if not total:
            return resumo

        if len(alvos) == total:
            self._log(f"🔎 Verificando respostas de {total} contato(s)...")
        else:
            self._log(
                f"🔎 Verificando respostas: {total} conversa(s) "
                f"para {len(alvos)} linha(s) da planilha."
            )
        pendentes = dict(mapa)

        # --- passada 1: de graça, sem digitar nada ---
        # O #pane-side já traz ~71 linhas renderizadas. Quando a campanha foi a
        # última coisa que aconteceu na conta, isso resolve a maioria.
        try:
            leituras = linha_conversa.ler_linhas(self.driver, agora)
            for leitura in leituras:
                num = leitura.get("numero")
                if num in pendentes:
                    for idx in pendentes.pop(num):
                        self._registrar(df, idx, leitura, resumo, agora)
            # Segunda volta na MESMA leitura, agora pelo nome: quem está salvo
            # na agenda aparece sem número e não teve chance na volta acima.
            self._casar_por_nome(df, leituras, pendentes, nomes, resumo, agora)
        except Exception as e:
            self._log(f"Leitura inicial da lista falhou ({e.__class__.__name__}); usando a busca.")

        if pendentes:
            self._log(
                f"{total - len(pendentes)} encontrado(s) direto na lista; "
                f"buscando os outros {len(pendentes)}."
            )
        self._feitas = total - len(pendentes)
        self._progresso(self._feitas, total)

        # --- passada 2: busca, um por um ---
        nao_achados = self._passada_de_busca(
            df, pendentes, resumo, agora, total, 1, nomes
        )

        # --- retentativa: "não achei" pode ser só "ainda não sincronizou" ---
        if nao_achados and not resumo["interrompida"]:
            self._log(
                f"{len(nao_achados)} conversa(s) não localizada(s). O WhatsApp Web "
                f"pode ainda estar sincronizando — esperando "
                f"{int(PAUSA_RETENTATIVA_SEG)}s para tentar de novo."
            )
            if self._dormir(PAUSA_RETENTATIVA_SEG):
                nao_achados = self._passada_de_busca(
                    df, nao_achados, resumo, agora, total, 2, nomes
                )
            else:
                resumo["interrompida"] = True

        resumo["nao_encontrados"] = len(nao_achados)
        self._log(
            f"✅ Verificação concluída: {resumo['respondeu']} linha(s) com resposta, "
            f"{resumo['nao_entregue']} não entregues, "
            f"{resumo['nao_encontrados']} conversa(s) não localizadas na lista."
        )
        return resumo

    def _passada_de_busca(self, df, pendentes: dict, resumo: dict, agora,
                          total: int, tentativa: int, nomes: Optional[dict] = None) -> dict:
        """
        Busca um número por vez e grava quem for encontrado.

        Devolve os que NÃO foram encontrados, no mesmo formato de `pendentes`,
        para o chamador poder tentar de novo. Quem não chegou a ser consultado
        (parada no meio) fica de fora: não foi procurado, então chamá-lo de
        "não encontrado" seria falso.
        """
        nao_achados = {}
        for num, indices in list(pendentes.items()):
            if self._parar():
                resumo["interrompida"] = True
                break
            try:
                linhas = self._buscar(num)
            except Exception as e:
                self._log(f"Busca falhou para um contato ({e.__class__.__name__}).")
                linhas = []

            achou = next((l for l in linhas if l.get("numero") == num), None)
            via = "numero"
            if not achou:
                achou = self._linha_de_contato_salvo(linhas, num, nomes or {})
                via = "contato-salvo"
            if achou:
                for idx in indices:
                    self._registrar(df, idx, achou, resumo, agora, via)
            else:
                # Conversa não encontrada nem pelo número, nem pelo nome, nem
                # pela regra do contato salvo. Não é erro do contato: a
                # conversa pode ter sido apagada, o WhatsApp Web pode não ter
                # sincronizado, ou o nome pode estar ambíguo demais para servir
                # de prova. Não grava nada — o silêncio é melhor que um "não
                # respondeu" que ninguém leu.
                nao_achados[num] = indices
                self._log_nao_encontrado(num, linhas, tentativa)
            self._feitas += 1
            self._progresso(self._feitas, total)
        return nao_achados

    def _casar_por_nome(self, df, leituras: list, pendentes: dict, nomes: dict,
                        resumo: dict, agora) -> None:
        """
        Casa pelo NOME as linhas da passada livre que não mostram número.

        Contato salvo na agenda aparece na lista pelo nome, e até aqui isso o
        condenava a "conversa não encontrada": nenhuma das duas passadas
        chegava nele, e "não encontrada" é o único desfecho que não escreve
        nada. Resultado prático, que foi o relato do cliente — o app não dizia
        se a mensagem tinha sido vista justamente para os contatos já salvos.

        **A ambiguidade tem dois lados, e os dois desqualificam o casamento.**
        Um nome que aparece em duas linhas da lista (dois "Isis Campos" na
        agenda) e uma linha que casa com dois nomes da planilha são a mesma
        falha vista de dois ângulos: não há como saber qual é qual, e escrever
        o estado de uma conversa na linha de outra pessoa não deixa nenhum
        rastro na tela. Nesses casos o contato continua pendente e vai para a
        busca, que filtra pelo número e é prova muito mais forte.
        """
        if not pendentes or not nomes:
            return

        pares = []
        for i, leitura in enumerate(leituras):
            # Quem mostra número já teve a sua chance na volta anterior, e o
            # número é sempre a prova mais forte.
            if leitura.get("numero"):
                continue
            titulo = leitura.get("titulo")
            for chave, numero in nomes.items():
                if numero in pendentes and linha_conversa.titulo_casa_com_nome(titulo, chave):
                    pares.append((numero, i, leitura))

        linhas_por_numero, numeros_por_linha = {}, {}
        for numero, i, _ in pares:
            linhas_por_numero.setdefault(numero, []).append(i)
            numeros_por_linha.setdefault(i, []).append(numero)

        for numero, indices_de_linha in linhas_por_numero.items():
            if len(indices_de_linha) != 1 or len(numeros_por_linha[indices_de_linha[0]]) != 1:
                file_logger.info(
                    "[varredura] NOME AMBIGUO numero=%s linhas=%s", numero,
                    len(indices_de_linha),
                )
                continue
            leitura = next(l for n, i, l in pares if n == numero)
            for idx in pendentes.pop(numero):
                self._registrar(df, idx, leitura, resumo, agora, "nome")

    def _linha_de_contato_salvo(self, linhas: list, num: str, nomes: dict):
        """
        A linha que a busca por NÚMERO devolveu para um contato salvo na agenda.

        Digitamos o número; o WhatsApp encontra o contato pela agenda e mostra
        o NOME dele. Casar de volta pelo número é impossível — é essa a razão
        de um contato salvo nunca ser encontrado. Duas provas, nesta ordem:

        1. O título casa com o `Nome` da planilha. Duas evidências
           independentes concordando (o número que filtrou a lista e o nome
           que o cliente digitou), e é a mais forte que existe aqui.
        2. Sobrou **uma única** conversa no filtro e ela não exibe outro
           número. A lista inteira foi filtrada pelo número que digitamos, e
           a única coisa que restou é a conversa dele.

        A regra 2 cobre o caso normal de a planilha e a agenda escreverem o
        nome de jeitos diferentes ("Isis" contra "Isis Campos - Pilates"), que
        é frequente o bastante para a regra 1 sozinha não resolver.

        Qualquer ambiguidade — duas ou mais conversas no filtro, ou uma
        conversa exibindo um número que não é o nosso — devolve None e a
        linha fica sem gravação. O silêncio continua sendo melhor que a
        invenção.
        """
        candidatas = [l for l in linhas if str(l.get("titulo") or "").strip()]
        if not candidatas:
            return None

        chave = next((c for c, n in nomes.items() if n == num), "")
        if chave:
            por_nome = [
                l for l in candidatas
                if linha_conversa.titulo_casa_com_nome(l.get("titulo"), chave)
            ]
            if len(por_nome) == 1:
                return por_nome[0]

        # `numero` vazio: a linha mostra um nome. Se mostrasse um número, ele
        # teria casado lá em cima — exibir OUTRO número é prova de que a busca
        # trouxe a conversa errada.
        if len(candidatas) == 1 and not candidatas[0].get("numero"):
            return candidatas[0]
        return None

    def _log_nao_encontrado(self, num: str, linhas: list, tentativa: int) -> None:
        """
        Diagnóstico do único desfecho que não escreve NADA na planilha.

        Antes disto, "não localizada" era um contador no resumo final e mais
        nada: nem qual número, nem o que a busca devolveu. Como a linha fica
        exatamente como estava, não sobrava evidência nenhuma de que algo tinha
        falhado — o cliente vê só um "-" na tela, idêntico ao de um contato
        ainda não verificado. Diagnosticar um caso destes custou seis sondas
        contra o WhatsApp Web real (12/09/2026); com esta linha, custa uma
        olhada no log.

        Vai no log de ARQUIVO, não no da tela, pelo mesmo motivo do
        `_registrar`: é evidência para auditoria, e o log da tela é do cliente.
        """
        linhas = linhas or []
        file_logger.info(
            "[varredura] NAO ENCONTRADO numero=%s tentativa=%s linhas_na_busca=%s "
            "numeros_vistos=%s titulos=%s",
            num,
            tentativa,
            len(linhas),
            [l.get("numero") for l in linhas if l.get("numero")],
            [str(l.get("titulo") or "")[:30] for l in linhas[:5]],
        )

    def _dormir(self, segundos: float) -> bool:
        """
        Espera podendo ser interrompida. Devolve False se o usuário parou — o
        botão Parar tem de continuar respondendo durante a pausa.
        """
        fim = time.monotonic() + segundos
        while time.monotonic() < fim:
            if self._parar():
                return False
            time.sleep(min(0.5, max(0.0, fim - time.monotonic())))
        return not self._parar()

    def _registrar(self, df, idx, leitura, resumo, agora, via: str = "numero"):
        # Diagnóstico no log de arquivo, não no log da tela: é ruído para o
        # cliente e é a ÚNICA forma de auditar depois por que uma linha foi
        # lida como foi. A decisão é por ausência de ícone, então a lista de
        # ícones crus é literalmente a evidência — sem ela, um "Lido" errado e
        # uma extração quebrada são indistinguíveis a posteriori.
        file_logger.info(
            "[varredura] linha=%s numero=%s estado=%s icones=%s horario=%r "
            "titulo_tem_numero=%s casou_por=%s",
            idx,
            leitura.get("numero") or "?",
            leitura.get("estado"),
            leitura.get("icones"),
            leitura.get("horario_texto"),
            bool(leitura.get("casa_por_numero")),
            via,
        )
        entrega = aplicar_leitura(df, idx, leitura, agora)
        if not entrega:
            return
        resumo["verificados"] += 1
        if entrega == ENTREGA_RESPONDEU:
            resumo["respondeu"] += 1
        elif entrega in (ENTREGA_NAO_ENTREGUE, ENTREGA_FALHOU):
            resumo["nao_entregue"] += 1
