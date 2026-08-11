@echo off
echo ============================================
echo   Build - WhatsApp Automacao (.exe)
echo ============================================
echo.

:: Gera o CSS Tailwind local antes de empacotar
where node >nul 2>&1
if errorlevel 1 (
    echo ERRO: Node.js nao encontrado. Instale o Node.js para gerar o CSS.
    pause
    exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
    echo ERRO: npm nao encontrado. Instale o Node.js com npm para gerar o CSS.
    pause
    exit /b 1
)

if not exist "node_modules\.bin\tailwindcss.cmd" (
    echo Instalando dependencias do frontend...
    call npm ci --ignore-scripts --no-audit --no-fund
    if errorlevel 1 (
        echo.
        echo ERRO ao instalar as dependencias do frontend.
        pause
        exit /b 1
    )
    echo.
)

echo Gerando CSS Tailwind local...
call npm run build:css
if errorlevel 1 (
    echo.
    echo ERRO ao gerar o CSS Tailwind.
    pause
    exit /b 1
)

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
    --noconfirm ^
    --name "WhatsAppAutomacao" ^
    --onedir ^
    --console ^
    --icon=NONE ^
    --collect-submodules=hypercorn ^
    --collect-submodules=fastapi ^
    --collect-submodules=starlette ^
    --collect-submodules=multipart ^
    --collect-submodules=selenium ^
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
