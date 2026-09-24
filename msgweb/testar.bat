@echo off
REM ============================================================
REM  Sobe o servidor com a planilha de TESTE zerada.
REM
REM  A planilha de teste e' a bancada (46 casos). Um envio de
REM  verdade escreve nela, e na rodada seguinte quase toda linha
REM  esta com Enviado=X e e' PULADA. Este comando regenera a
REM  planilha do seed versionado (test_contatos.csv) antes de
REM  subir o servidor, entao toda execucao comeca limpa.
REM
REM  Para editar os casos de teste: abra test_contatos.csv.
REM  O .xlsx e' derivado e pode ser apagado a qualquer momento.
REM
REM  ATENCAO: so ASCII neste arquivo. O cmd.exe le .bat na
REM  codepage OEM, e um byte acentuado dentro de um echo corrompe
REM  o parsing do bloco if que o envolve (ver CLAUDE.md).
REM ============================================================
setlocal
cd /d "%~dp0"
set WDM_SSL_VERIFY=0

".\venv\Scripts\python.exe" ".\gerar_planilha_teste.py"
if errorlevel 1 (
    echo.
    echo ERRO: nao foi possivel gerar a planilha de teste.
    pause
    exit /b 1
)

REM Marcador de execucao interrompida. Ele descreve o envio de uma
REM planilha que acabou de ser jogada fora, entao o aviso de
REM "execucao interrompida" na proxima tela falaria de pendencias
REM que nao existem mais. Apagar aqui e' o unico jeito de a
REM bancada comecar limpa DE VERDADE.
if exist "uploads\envio_em_andamento.json" del /q "uploads\envio_em_andamento.json"

echo.
echo Servidor em http://localhost:8000   (CTRL+C encerra)
echo.
".\venv\Scripts\python.exe" ".\app.py" --planilha test
pause
