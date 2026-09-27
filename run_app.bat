@echo off
title SEFAZ DF-e Client & Validador XML
cd /d "%~dp0"
echo Iniciando a Interface Grafica do SEFAZ DF-e...
python sefaz_python_client\main_gui.py
if errorlevel 1 (
    echo.
    echo Ocorreu um erro ao iniciar a aplicacao. Verifique se o Python e as dependencias estao instaladas:
    echo pip install httpx cryptography
    pause
)

