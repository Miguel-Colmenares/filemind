@echo off
rem Abre el selector de carpetas de Windows que usa FileMind cuando corre en Docker (puerto 8765, solo este PC).
start "" pythonw "%~dp0selector_carpetas.py"
