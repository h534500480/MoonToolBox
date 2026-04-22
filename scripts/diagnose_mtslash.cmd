@echo off
setlocal
set "ROOT=%~dp0.."
set "PY=%ROOT%\runtime\python\python.exe"
if exist "%PY%" goto run
set "PY=python"
:run
"%PY%" "%~dp0diagnose_mtslash.py" %*
pause
