@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    call :create_venv
    if errorlevel 1 goto python_missing
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check .
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m autojob init
if errorlevel 1 goto failed
echo Job Hunting instalado.
exit /b 0

:create_venv
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" -m venv ".venv"
    if errorlevel 1 exit /b 1
    exit /b 0
)
if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python313\python.exe" (
    "%USERPROFILE%\AppData\Local\Programs\Python\Python313\python.exe" -m venv ".venv"
    if errorlevel 1 exit /b 1
    exit /b 0
)
py -3.13 -m venv ".venv"
exit /b %ERRORLEVEL%

:python_missing
echo Instala Python 3.13 de 64 bits desde https://www.python.org/downloads/windows/
echo Incluye el lanzador py y vuelve a abrir Job Hunting.
pause
exit /b 1

:failed
echo La instalacion no termino. Revisa el mensaje anterior y vuelve a intentarlo.
pause
exit /b 1
