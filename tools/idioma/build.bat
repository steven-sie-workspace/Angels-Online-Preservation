@echo off
rem Compila dinput8.dll (x86) con las Build Tools de Visual Studio.
setlocal
set "VCVARS=%ProgramFiles(x86)%\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars32.bat"
if exist "%VCVARS%" goto compilar
for /f "usebackq delims=" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -find VC\Auxiliary\Build\vcvars32.bat`) do set "VCVARS=%%i"
:compilar
call "%VCVARS%" >nul || exit /b 1
cd /d "%~dp0"
cl /nologo /utf-8 /O2 /MT /W3 /LD dinput8.c /link /DEF:dinput8.def /OUT:dinput8.dll kernel32.lib user32.lib || exit /b 1
del /q dinput8.obj dinput8.lib dinput8.exp 2>nul
echo OK: %~dp0dinput8.dll
