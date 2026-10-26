@echo off
REM Graba una sesion en Venus (Global oficial) pasando por tools\proxy.py.
REM Deja todo en logs\proxy\, con marca de tiempo, para tools\medir_regen.py.
REM
REM Apunta el server.xml del cliente de Global con el que se juega a
REM 127.0.0.1 (copia en server.xml.bak) y lo devuelve a su sitio al cerrar.
REM Venus es el servidor 2 de ese server.xml: 20.2.137.147, puerto 28111.
REM
REM El cliente es el instalado en C:\UserJoy (el GameDir de su reg.ini), NO
REM la copia "Angels Online Global" del repo, que solo es de consulta. Si
REM esta en otro sitio: grabar_venus.bat "D:\ruta\Angels Online Global"
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set "GLOBAL_DIR=%~1"
if "%GLOBAL_DIR%"=="" set "GLOBAL_DIR=C:\UserJoy\Angels Online Global"
set "GLOBAL_XML=%GLOBAL_DIR%\server.xml"
if not exist "%GLOBAL_XML%" (
    echo No encuentro "%GLOBAL_XML%"
    pause
    exit /b 1
)
echo.
echo  1. Deja esta ventana abierta y abre el juego de Global. Elige Venus.
echo  2. Para terminar: Ctrl+C aqui, y a "Terminate batch job (Y/N)?" contesta N
echo     para que se restaure el server.xml.
echo.
py -3 tools\proxy.py --server-xml "%GLOBAL_XML%" --puerto 28111
echo.
echo Restaurando el server.xml de Global...
py -3 tools\proxy.py --server-xml "%GLOBAL_XML%" --restaurar
echo.
echo Para medir la regeneracion: medir_regen.bat
pause
