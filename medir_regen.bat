@echo off
REM Mide la regeneracion de HP/MP (sentado y de pie) de una grabacion.
REM Sin argumentos usa la sesion de mundo mas reciente de logs\proxy\;
REM tambien se le puede arrastrar encima un *_orden.jsonl.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set "F=%~1"
if "%F%"=="" (
    for /f "delims=" %%f in ('dir /b /o-d "logs\proxy\mundo_*_orden.jsonl" 2^>nul') do (
        if not defined F set "F=logs\proxy\%%f"
    )
)
if "%F%"=="" (
    echo No hay grabaciones en logs\proxy\. Graba primero con grabar_venus.bat
    pause
    exit /b 1
)
REM Con --cambios lista ademas cada sentarse/levantarse con su segundo.
py -3 tools\medir_regen.py "%F%"
pause
