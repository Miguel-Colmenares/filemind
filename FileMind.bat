@echo off
rem Abre FileMind como aplicacion de escritorio (API + puente de WhatsApp + ventana).
cd /d "%~dp0backend"
set PYTHONUTF8=1
start "" "%~dp0.venv\Scripts\pythonw.exe" -m filemind escritorio
