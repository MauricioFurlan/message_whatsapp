@echo off
echo ============================================
echo   Build - WhatsApp Automacao (.exe)
echo ============================================
echo.

:: Versão via parâmetro (ex: build.bat 1.2.0)
if "%~1"=="" (
    echo ERRO: Informe a versao como parametro.
    echo Uso: build.bat 1.2.0
    pause
    exit /b 1
)
set "VERSION=%~1"
echo Versao: %VERSION%
echo.

:: Atualiza version.py com a versão informada
(
echo # Versao do aplicativo - atualizada automaticamente pelo build.bat
echo APP_VERSION = "%VERSION%"
)> version.py
echo version.py atualizado para %VERSION%
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

:: Cria uploads/ no dist com planilha modelo (sempre limpa, um contato de teste)
python gerar_planilha_modelo.py "dist\WhatsAppAutomacao\uploads\contatos.xlsx"

:: Copia LEIA-ME
copy "LEIA-ME_CLIENTE.txt" "dist\WhatsAppAutomacao\LEIA-ME.txt" >nul 2>&1

echo.
echo Gerando arquivo .zip...

:: Remove zip anterior se existir
if exist "dist\WhatsAppAutomacao-v%VERSION%.zip" del /q "dist\WhatsAppAutomacao-v%VERSION%.zip"

:: Compacta a pasta usando PowerShell
powershell -NoProfile -Command "Compress-Archive -Path 'dist\WhatsAppAutomacao' -DestinationPath 'dist\WhatsAppAutomacao-v%VERSION%.zip' -Force"

if %errorlevel% neq 0 (
    echo.
    echo AVISO: Falha ao gerar o .zip. A pasta dist\WhatsAppAutomacao ainda esta disponivel.
) else (
    echo   Arquivo gerado: dist\WhatsAppAutomacao-v%VERSION%.zip
)

echo.
echo ============================================
echo   Build concluido! (v%VERSION%)
echo ============================================
echo.
echo   Pasta de distribuicao: dist\WhatsAppAutomacao\
echo   Arquivo zip: dist\WhatsAppAutomacao-v%VERSION%.zip
echo.
echo   O cliente executa: WhatsAppAutomacao.exe
echo ============================================
echo.
pause
