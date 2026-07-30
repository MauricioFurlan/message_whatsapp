@echo off
echo ============================================
echo   Build - WhatsApp Automacao (.exe)
echo ============================================
echo.

:: Verifica se PyInstaller está instalado
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo Instalando PyInstaller...
    pip install pyinstaller
    echo.
)

:: Limpa builds anteriores
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build
if exist "WhatsAppAutomacao.spec" del /q WhatsAppAutomacao.spec

echo Gerando executavel...
echo.

:: Empacota com PyInstaller
pyinstaller ^
    --name "WhatsAppAutomacao" ^
    --onedir ^
    --console ^
    --icon=NONE ^
    --collect-submodules=hypercorn ^
    --collect-submodules=fastapi ^
    --collect-submodules=starlette ^
    --collect-submodules=multipart ^
    --exclude-module=tkinter ^
    --exclude-module=matplotlib ^
    --exclude-module=numpy.testing ^
    --exclude-module=pytest ^
    --exclude-module=uvicorn ^
    launcher.py

if %errorlevel% neq 0 (
    echo.
    echo ERRO no build! Verifique as mensagens acima.
    pause
    exit /b 1
)

echo.
echo Copiando arquivos adicionais...

:: Copia static/ para dist
xcopy "static" "dist\WhatsAppAutomacao\static\" /E /I /Y >nul

:: Copia uploads/ para dist (planilha modelo)
xcopy "uploads" "dist\WhatsAppAutomacao\uploads\" /E /I /Y >nul

:: Copia LEIA-ME
copy "LEIA-ME_CLIENTE.txt" "dist\WhatsAppAutomacao\LEIA-ME.txt" >nul 2>&1

echo.
echo Gerando arquivo .zip...

:: Remove zip anterior se existir
if exist "dist\WhatsAppAutomacao.zip" del /q "dist\WhatsAppAutomacao.zip"

:: Compacta a pasta usando PowerShell
powershell -NoProfile -Command "Compress-Archive -Path 'dist\WhatsAppAutomacao' -DestinationPath 'dist\WhatsAppAutomacao.zip' -Force"

if %errorlevel% neq 0 (
    echo.
    echo AVISO: Falha ao gerar o .zip. A pasta dist\WhatsAppAutomacao ainda esta disponivel.
) else (
    echo   Arquivo gerado: dist\WhatsAppAutomacao.zip
)

echo.
echo ============================================
echo   Build concluido!
echo ============================================
echo.
echo   Pasta de distribuicao: dist\WhatsAppAutomacao\
echo   Arquivo zip: dist\WhatsAppAutomacao.zip
echo.
echo   O cliente executa: WhatsAppAutomacao.exe
echo ============================================
echo.
pause
