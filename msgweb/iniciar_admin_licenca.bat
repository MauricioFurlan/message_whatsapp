@echo off
setlocal
title Admin - Gerenciador de Licencas
cd /d "%~dp0"

if not exist ".\admin_licenca.py" goto missing_script

if exist ".\venv\Scripts\python.exe" goto run_venv
where py >nul 2>&1
if not errorlevel 1 goto run_py
where python >nul 2>&1
if not errorlevel 1 goto run_python
goto missing_python

:run_venv
".\venv\Scripts\python.exe" ".\admin_licenca.py"
set "EXIT_CODE=%ERRORLEVEL%"
goto finished

:run_py
py -3 ".\admin_licenca.py"
set "EXIT_CODE=%ERRORLEVEL%"
goto finished

:run_python
python ".\admin_licenca.py"
set "EXIT_CODE=%ERRORLEVEL%"
goto finished

:missing_script
echo ERRO: admin_licenca.py nao foi encontrado em:
echo %CD%
set "EXIT_CODE=1"
goto finished

:missing_python
echo ERRO: Python nao foi encontrado.
echo Crie o ambiente virtual em .\venv ou instale o Python 3.
set "EXIT_CODE=1"

:finished
echo.
if not "%EXIT_CODE%"=="0" echo O administrador terminou com codigo %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
