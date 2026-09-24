@echo off
REM ============================================================
REM  Roda a suite inteira (Python + Node) e mostra o resumo.
REM
REM    rodar_testes.bat              tudo (~2 min)
REM    rodar_testes.bat --rapido     pula os lentos (~25 s)
REM    rodar_testes.bat --so e2e     so um grupo
REM
REM  A logica esta no rodar_testes.py — aqui so o atalho. Nao
REM  encha este arquivo de if/echo: o cmd.exe le .bat na codepage
REM  OEM e um byte acentuado corrompe o bloco (ver CLAUDE.md).
REM ============================================================
setlocal
cd /d "%~dp0"
".\venv\Scripts\python.exe" ".\rodar_testes.py" %*
set CODIGO=%errorlevel%
echo.
pause
exit /b %CODIGO%
