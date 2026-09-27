@echo off
title Compilar SEFAZ DF-e para Executavel (.EXE)
cd /d "%~dp0"
echo ==============================================================
echo  Compilador SEFAZ DF-e Client e Validador XML para EXE
echo ==============================================================
echo.

echo 1. Verificando PyInstaller...
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller nao esta instalado. Instalando via pip...
    pip install pyinstaller
    if errorlevel 1 (
        echo Falha ao instalar PyInstaller. Verifique sua conexao ou permissoes.
        pause
        exit /b 1
    )
)

echo.
echo 2. Compilando aplicacao em executavel unico (.exe)...
pyinstaller --noconfirm --onedir --windowed ^
    --name "SefazDFeClient" ^
    --add-data "sefaz_python_client/core;core" ^
    --add-data "sefaz_python_client/gui;gui" ^
    --hidden-import "cryptography" ^
    --hidden-import "httpx" ^
    --hidden-import "tkinter" ^
    sefaz_python_client/main_gui.py

if errorlevel 1 (
    echo.
    echo Ocorreu um erro durante a compilacao com o PyInstaller.
    pause
    exit /b 1
)

echo.
echo ==============================================================
echo  Compilacao concluida com sucesso!
echo  O executavel esta disponivel na pasta: dist\SefazDFeClient\
echo ==============================================================
pause

